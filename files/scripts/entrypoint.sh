#!/usr/bin/env bash
#
# variables:
# - ENC_VIEWER_PASSWORD: password for the HAProxy Basic Authentication user (default: "puppet")
# - USE_SSL: either "true" or "false" to enable/disable SSL in HAProxy
# - SSL_CERT_PATH: path to the SSL certificate file (default: "/etc/ssl/private/server.pem")
# - USE_SQLITE_WEB: either "true" or "false" to enable/disable sqlite-web interface
#
set -e

# ============================== #
# set django backend for HAProxy #
# ============================== #
if [ "$DEBUG" = "true" ]; then
    export ENCOMPASS_BACKEND="server django 127.0.0.1:8000 check"
else
    export ENCOMPASS_BACKEND="server django unix@/run/encompass.sock check"
fi

# ================================================== #
# set HAProxy authentication if password is provided #
# ================================================== #
if [ -n "$ENC_VIEWER_PASSWORD" ]; then
    echo "==> Enabling HAProxy Basic Auth..."
    export ENC_VIEWER_AUTH="
    http-request auth unless is_healthcheck or { http_auth(users) }
    http-request deny unless { http_auth_user() encompass }
"
    HASH=$(openssl passwd -6 "$ENC_VIEWER_PASSWORD")
    export AUTH_LIST="
# Authentication
userlist users
    user encompass password $HASH
"
else
    echo "==> Disabling HAProxy Basic Auth..."
    export ENC_VIEWER_AUTH=""
    export AUTH_LIST=""
fi

# ============================================ #
# set SSL configuration for HAProxy if enabled #
# ============================================ #
if [ "$USE_SSL" = "true" ]; then
    echo "==> Enabling SSL in HAProxy"
    export ENCOMPASS_UI_SSL="
    bind *:8443 ssl crt $SSL_CERT_PATH
    http-request    set-header X-Forwarded-Proto https
    redirect scheme https code 301 if !{ ssl_fc }

"
    export ENC_UI_SSL="
    bind *:8444     ssl crt $SSL_CERT_PATH
    http-request    set-header X-Forwarded-Proto https
    redirect scheme https code 301 if !{ ssl_fc }

"
    export SQLITE_WEB_SSL="
    bind            *:8445 ssl crt $SSL_CERT_PATH
    redirect        scheme https code 301 if !{ ssl_fc }
    http-request    set-header X-Forwarded-Proto https
    default_backend sqlite_web_backend

"
else
    echo "==> Disabling SSL in HAProxy"
    export ENC_UI_SSL=""
    export SQLITE_WEB_SSL=""
fi

# ====================================================== #
# set HAProxy configuration for sqlite-web UI if enabled #
# ====================================================== #
if [ "$USE_SQLITE_WEB" = "true" ]; then
    echo "==> Enabling Sqlite-web..."
    export SQLITE_WEB_FRONTEND="frontend sqlite_web_frontend
    mode http
    bind *:8082
$SQLITE_WEB_SSL
    default_backend sqlite_web_backend
"
    export SQLITE_WEB_BACKEND="backend sqlite_web_backend
    mode http
    server sqlite_web 127.0.0.1:8002 check

"
else
    echo "==> Disabling Sqlite-web"
    rm -f /etc/supervisor/conf.d/sqlite-web.conf
    export SQLITE_WEB_FRONTEND=""
    export SQLITE_WEB_BACKEND=""
fi

# ========================================== #
# set HAProxy configuration for ENC frontend #
# ========================================== #
export HAPROXY_ENC_FRONTEND="frontend enc_frontend
    mode http
    bind *:8081
${ENC_UI_SSL}
    acl          flask_urls path_reg ^/(hosts|groups|users|healthz)/$
    acl          is_healthcheck path /healthz
${ENC_VIEWER_AUTH}
    http-request redirect code 301 location %[path,regsub(/$,)] if flask_urls
    http-request set-log-level silent if is_healthcheck

    http-request del-header X-Haproxy-Proxy
    http-request del-header X-Forwarded-For
    http-request set-header X-Haproxy-Proxy true

    default_backend enc_backend
"

envsubst </root/haproxy.cfg.template >/etc/haproxy/haproxy.cfg
rm /root/haproxy.cfg.template

exec /usr/bin/supervisord --configuration /etc/supervisor/supervisord.conf
