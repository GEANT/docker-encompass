#!/usr/bin/env bash
#
# variables:
# - ENC_VIEWER_PASSWORD: password for optional basic auth on read-only ENC endpoint (user: encompass)
# - ENC_USE_SSL: either "true" or "false" to enable/disable SSL listeners in Nginx
# - ENC_SSL_CERT_PATH: path to the SSL certificate PEM file
# - ENC_SSL_KEY_PATH: path to the SSL private key PEM file
#
set -e

parse_mysql_node_endpoint() {
    local node="$1"
    local default_port="$2"
    local host=""
    local port=""

    if [[ "$node" =~ ^\[(.*)\]:([0-9]+)$ ]]; then
        host="${BASH_REMATCH[1]}"
        port="${BASH_REMATCH[2]}"
    elif [[ "$node" =~ ^\[(.*)\]$ ]]; then
        host="${BASH_REMATCH[1]}"
        port="$default_port"
    elif [[ "$node" == *:* ]] && [[ "$node" != *:*:* ]]; then
        host="${node%%:*}"
        port="${node##*:}"
    elif [[ "$node" == *:*:* ]]; then
        host="$node"
        port="$default_port"
    else
        host="$node"
        port="$default_port"
    fi

    printf '%s\t%s\n' "$host" "$port"
}

# ========== #
# set up Git #
# ========== #
/usr/local/bin/git-setup.sh

# ================================== #
# set django backend for Nginx proxy #
# ================================== #
if [ "$DEBUG" = "true" ]; then
    export DJANGO_BACKEND="server 127.0.0.1:8000;"
else
    export DJANGO_BACKEND="server unix:/run/encompass.sock;"
fi

# ================================================================= #
# MySQL endpoint mode driven by MYSQL_NODES (comma-separated):      #
# - 1 node : direct endpoint (single instance / HAProxy / ProxySQL) #
# - >1 nodes: generate HAProxy config and bring it up via supervisord#
# Optional: MYSQL_MONITORING_PORT - HTTP health-check port (9200)   #
# Optional: MYSQL_HAPROXY_CHECK_USER - MySQL-protocol check user    #
# ================================================================= #
trimmed_mysql_nodes=$(echo "${MYSQL_NODES:-}" | tr -d '[:space:]')
if [ -n "$trimmed_mysql_nodes" ]; then
    monitor_port="$(echo "${MYSQL_MONITORING_PORT:-}" | tr -d '[:space:]')"
    haproxy_check_user="$(echo "${MYSQL_HAPROXY_CHECK_USER:-}" | tr -d '[:space:]')"

    if [ -n "$monitor_port" ] && ! [[ "$monitor_port" =~ ^[0-9]+$ ]]; then
        echo "[ERROR] MYSQL_MONITORING_PORT must be a numeric port"
        exit 1
    fi

    if [ -n "$monitor_port" ] && [ -n "$haproxy_check_user" ]; then
        echo "[ERROR] MYSQL_MONITORING_PORT and MYSQL_HAPROXY_CHECK_USER are mutually exclusive"
        echo "[ERROR] Set only one: HTTP check (MYSQL_MONITORING_PORT) or MySQL-protocol check (MYSQL_HAPROXY_CHECK_USER)"
        exit 1
    fi

    IFS=',' read -r -a mysql_nodes_array <<<"$trimmed_mysql_nodes"

    valid_nodes=()
    for node in "${mysql_nodes_array[@]}"; do
        [ -n "$node" ] && valid_nodes+=("$node")
    done

    node_count=${#valid_nodes[@]}
    mysql_default_port="3306"

    if [ "$node_count" -eq 1 ]; then
        single_node="${valid_nodes[0]}"
        IFS=$'\t' read -r parsed_host parsed_port <<<"$(parse_mysql_node_endpoint "$single_node" "$mysql_default_port")"
        export MYSQL_HOST="$parsed_host"
        export MYSQL_PORT="$parsed_port"
        echo "==> MySQL: Single node, direct endpoint ${MYSQL_HOST}:${MYSQL_PORT}"

    elif [ "$node_count" -gt 1 ]; then
        # Build HAProxy server lines
        haproxy_servers=""
        server_idx=1
        for node in "${valid_nodes[@]}"; do
            IFS=$'\t' read -r node_host node_port <<<"$(parse_mysql_node_endpoint "$node" "$mysql_default_port")"
            if [ -n "$monitor_port" ]; then
                check_opts="check port ${monitor_port} inter 2s rise 2 fall 3"
            else
                check_opts="check inter 2s rise 2 fall 3"
            fi
            haproxy_servers+="    server galera${server_idx} ${node_host}:${node_port} ${check_opts}"
            haproxy_servers+=$'\n'
            server_idx=$((server_idx + 1))
        done

        # Health-check option line (only one can be active)
        if [ -n "$monitor_port" ]; then
            haproxy_check_option=$'    option httpchk HEAD /\n    http-check expect status 200'
        elif [ -n "$haproxy_check_user" ]; then
            haproxy_check_option="    option mysql-check user ${haproxy_check_user} post-41"
        else
            haproxy_check_option="    option tcp-check"
        fi

        mkdir -p /etc/haproxy
        cat >/etc/haproxy/haproxy.cfg <<HAPROXYEOF
global
    log stdout format raw local0
    maxconn 4096

defaults
    log global
    mode tcp
    option tcplog
    option dontlog-normal
    timeout connect 5s
    timeout client 1h
    timeout server 1h

frontend mysql_front
    bind /run/haproxy-mysql.sock
    default_backend galera_cluster

backend galera_cluster
    balance leastconn
${haproxy_check_option}
${haproxy_servers}
HAPROXYEOF

        export MYSQL_HOST=""
        export MYSQL_PORT=""
        echo "==> MySQL: ${node_count} nodes, HAProxy enabled on /run/haproxy-mysql.sock"
        if [ -n "$monitor_port" ]; then
            echo "==> MySQL: health-check via HTTP on port ${monitor_port}"
        elif [ -n "$haproxy_check_user" ]; then
            echo "==> MySQL: health-check via mysql-check user ${haproxy_check_user}"
        else
            echo "==> MySQL: health-check via TCP"
        fi
    fi
fi

# ===================================================== #
# set ENC read-only basic auth if password is provided  #
# ===================================================== #
if [ -n "$ENC_VIEWER_PASSWORD" ]; then
    echo "==> Enabling Nginx Basic Auth for ENC read-only endpoint..."
    HASH=$(openssl passwd -6 "$ENC_VIEWER_PASSWORD")
    printf "encompass:%s\n" "$HASH" >/etc/nginx/.htpasswd_viewer
    chmod 600 /etc/nginx/.htpasswd_viewer
    export ENC_VIEWER_AUTH='auth_basic "ENC Viewer";
            auth_basic_user_file /etc/nginx/.htpasswd_viewer;'
else
    echo "==> Disabling Nginx Basic Auth for ENC read-only endpoint..."
    rm -f /etc/nginx/.htpasswd_viewer
    export ENC_VIEWER_AUTH=""
fi

# ========================================== #
# set SSL configuration for Nginx if enabled #
# ========================================== #
if [ "$ENC_USE_SSL" = "true" ]; then
    echo "==> Enabling SSL in Nginx"

    if [ -z "$ENC_SSL_CERT_PATH" ] || [ -z "$ENC_SSL_KEY_PATH" ]; then
        echo "[ERROR] ENC_USE_SSL=true requires both ENC_SSL_CERT_PATH and ENC_SSL_KEY_PATH to be set"
        exit 1
    fi

    # shellcheck disable=SC2016 # it doesn't have to expand here
    export ENCOMPASS_HTTP_REDIRECT='return 301 https://$host:8443$request_uri;'
    # shellcheck disable=SC2016 # it doesn't have to expand here
    export ENC_HTTP_REDIRECT='return 301 https://$host:8444$request_uri;'

    export ENCOMPASS_SSL_SERVER="

    server {
        listen 8443 ssl;
        ssl_certificate ${ENC_SSL_CERT_PATH};
        ssl_certificate_key ${ENC_SSL_KEY_PATH};

        location /static/ {
            alias /code/static/static/;
            try_files \$uri =404;
        }

        location ~ ^/(hosts|groups)(/|$) {
            return 403;
        }

        location / {
            proxy_set_header Host \$host;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto https;
            proxy_pass http://django_backend;
        }
    }
"

    export ENC_SSL_SERVER="

    server {
        listen 8444 ssl;
        ssl_certificate ${ENC_SSL_CERT_PATH};
        ssl_certificate_key ${ENC_SSL_KEY_PATH};

        location = /healthz {
            proxy_set_header Host \$host;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto https;
            proxy_set_header X-External-Proxy true;
            proxy_pass http://django_backend;
        }

        location ~ ^/(hosts|groups)(/|$) {
            limit_except GET HEAD OPTIONS {
                deny all;
            }
            ${ENC_VIEWER_AUTH}
            proxy_set_header Host \$host;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto https;
            proxy_set_header X-External-Proxy true;
            proxy_pass http://django_backend;
        }

        location / {
            return 404;
        }
    }
"
else
    echo "==> Disabling SSL in Nginx"
    export ENCOMPASS_HTTP_REDIRECT=""
    export ENC_HTTP_REDIRECT=""
    export ENCOMPASS_SSL_SERVER=""
    export ENC_SSL_SERVER=""
fi

# shellcheck disable=SC2016 # variables here are like a docstring for envsubst
envsubst '${DJANGO_BACKEND} ${ENC_VIEWER_AUTH} ${ENCOMPASS_HTTP_REDIRECT} ${ENC_HTTP_REDIRECT} ${ENCOMPASS_SSL_SERVER} ${ENC_SSL_SERVER}' </root/.templates/nginx.conf.template >/etc/nginx/nginx.conf

exec /usr/bin/supervisord --configuration /etc/supervisor/supervisord.conf
