#!/usr/bin/env bash
#
# variables:
# - ENC_VIEWER_PASSWORD: password for optional basic auth on read-only ENC endpoint (user: encompass)
# - USE_SSL: either "true" or "false" to enable/disable SSL listeners in Nginx
# - SSL_CERT_PATH: path to the SSL certificate/key PEM file (default: "/etc/ssl/private/server.pem")
# - USE_SQLITE_WEB: either "true" or "false" to enable/disable sqlite-web interface
#
set -e

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
    export ENCOMPASS_HTTP_REDIRECT='return 301 https://$host:8443$request_uri;'
    export ENC_HTTP_REDIRECT='return 301 https://$host:8444$request_uri;'

    export ENCOMPASS_SSL_SERVER="
    server {
        listen 8443 ssl;
        ssl_certificate ${SSL_CERT_PATH};
        ssl_certificate_key ${SSL_CERT_PATH};

        location /static/ {
            alias /code/static/static/;
            try_files \$uri =404;
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
        ssl_certificate_key ${SSL_CERT_PATH};

        location = /healthz {
            proxy_set_header Host \$host;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto https;
            proxy_set_header X-External-Proxy true;
            proxy_pass http://django_backend;
        }

        location / {
            if (\$request_method !~ ^(GET|HEAD|OPTIONS)$) {
                return 403;
            }
            ${ENC_VIEWER_AUTH}
            proxy_set_header Host \$host;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto https;
            proxy_set_header X-External-Proxy true;
            proxy_pass http://django_backend;
        }
    }
"

    export SQLITE_WEB_SSL_SERVER="
    server {
        listen 8445 ssl;
        ssl_certificate ${SSL_CERT_PATH};
        ssl_certificate_key ${SSL_CERT_PATH};

        location / {
            proxy_set_header Host \$host;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto https;
            proxy_pass http://127.0.0.1:8002;
        }
    }
"
else
    echo "==> Disabling SSL in Nginx"
    export ENCOMPASS_HTTP_REDIRECT=""
    export ENC_HTTP_REDIRECT=""
    export ENCOMPASS_SSL_SERVER=""
    export ENC_SSL_SERVER=""
    export SQLITE_WEB_SSL_SERVER=""
fi

# ==================================================== #
# set Nginx configuration for sqlite-web if requested #
# ==================================================== #
if [ "$USE_SQLITE_WEB" = "true" ]; then
    echo "==> Enabling Sqlite-web..."
    if [ "$USE_SSL" = "true" ]; then
        export SQLITE_HTTP_REDIRECT='return 301 https://$host:8445$request_uri;'
    else
        export SQLITE_HTTP_REDIRECT=""
    fi

    export SQLITE_WEB_SERVER="
    server {
        listen 8082;
        ${SQLITE_HTTP_REDIRECT}

        location / {
            proxy_set_header Host \$host;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
            proxy_pass http://127.0.0.1:8002;
        }
    }
"
else
    echo "==> Disabling Sqlite-web"
    rm -f /etc/supervisor/conf.d/sqlite-web.conf
    export SQLITE_HTTP_REDIRECT=""
    export SQLITE_WEB_SERVER=""
    export SQLITE_WEB_SSL_SERVER=""
fi


# shellcheck disable=SC2016 # variables are just like a docstring for envsubst
envsubst '${DJANGO_BACKEND} ${ENC_VIEWER_AUTH} ${ENCOMPASS_HTTP_REDIRECT} ${ENC_HTTP_REDIRECT} ${SQLITE_HTTP_REDIRECT} ${ENCOMPASS_SSL_SERVER} ${ENC_SSL_SERVER} ${SQLITE_WEB_SERVER} ${SQLITE_WEB_SSL_SERVER}' </root/nginx.conf.template >/etc/nginx/nginx.conf
rm /root/nginx.conf.template

exec /usr/bin/supervisord --configuration /etc/supervisor/supervisord.conf
