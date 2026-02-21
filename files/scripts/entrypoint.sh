#!/usr/bin/env bash
#
# variables:
# - ENC_VIEWER_PASSWORD: password for optional basic auth on read-only ENC endpoint (user: encompass)
# - USE_SSL: either "true" or "false" to enable/disable SSL listeners in Nginx
# - SSL_CERT_PATH: path to the SSL certificate PEM file
# - SSL_KEY_PATH: path to the SSL private key PEM file
#
set -e

# ================================== #
# set git authentication variables   #
# ================================== #
/usr/local/bin/git-setup.sh

# ================================== #
# set django backend for Nginx proxy #
# ================================== #
if [ "$DEBUG" = "true" ]; then
    export DJANGO_BACKEND="server 127.0.0.1:8000;"
else
    export DJANGO_BACKEND="server unix:/run/encompass.sock;"
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
if [ "$USE_SSL" = "true" ]; then
    echo "==> Enabling SSL in Nginx"

    if [ -z "$SSL_CERT_PATH" ] || [ -z "$SSL_KEY_PATH" ]; then
        echo "[ERROR] USE_SSL=true requires both SSL_CERT_PATH and SSL_KEY_PATH to be set"
        exit 1
    fi

    # shellcheck disable=SC2016 # it doesn't have to expand here
    export ENCOMPASS_HTTP_REDIRECT='return 301 https://$host:8443$request_uri;'
    # shellcheck disable=SC2016 # it doesn't have to expand here
    export ENC_HTTP_REDIRECT='return 301 https://$host:8444$request_uri;'

    export ENCOMPASS_SSL_SERVER="
    server {
        listen 8443 ssl;
        ssl_certificate ${SSL_CERT_PATH};
        ssl_certificate_key ${SSL_KEY_PATH};

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
        ssl_certificate ${SSL_CERT_PATH};
        ssl_certificate_key ${SSL_KEY_PATH};

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

# shellcheck disable=SC2016 # variables are like a docstring for envsubst
envsubst '${DJANGO_BACKEND} ${ENC_VIEWER_AUTH} ${ENCOMPASS_HTTP_REDIRECT} ${ENC_HTTP_REDIRECT} ${ENCOMPASS_SSL_SERVER} ${ENC_SSL_SERVER}' </root/.nginx.conf.template >/etc/nginx/nginx.conf

exec /usr/bin/supervisord --configuration /etc/supervisor/supervisord.conf
