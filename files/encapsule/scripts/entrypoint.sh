#!/usr/bin/bash
set -e

export GIT_READ_ONLY=true
/usr/local/bin/git-setup.sh

# ===================================================== #
# set ENC read-only basic auth if password is provided  #
# ===================================================== #
if [ -n "${ENC_VIEWER_PASSWORD:-}" ]; then
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
ENC_CERT_PATH="${ENC_SSL_CERT_PATH:-${ENC_ENC_SSL_CERT_PATH:-}}"
ENC_KEY_PATH="${ENC_SSL_KEY_PATH:-${SSL_KEY_PATH:-}}"
ENCAPSULE_SSL_PORT="${ENCAPSULE_SSL_PORT:-8444}"

if [ "${ENC_USE_SSL:-false}" = "true" ]; then
	echo "==> Enabling SSL in Nginx"

	if [ -z "$ENC_CERT_PATH" ] || [ -z "$ENC_KEY_PATH" ]; then
		echo "[ERROR] ENC_USE_SSL=true requires ENC_SSL_CERT_PATH and ENC_SSL_KEY_PATH"
		exit 1
	fi

	# shellcheck disable=SC2016 # it doesn't have to expand here
	export ENC_HTTP_REDIRECT='return 301 https://$host:'"${ENCAPSULE_SSL_PORT}"'$request_uri;'

	export ENC_SSL_SERVER="

	server {
		listen ${ENCAPSULE_SSL_PORT} ssl;
		ssl_certificate ${ENC_CERT_PATH};
		ssl_certificate_key ${ENC_KEY_PATH};

		location /static/ {
			alias /code/encapsule/static/;
			try_files \$uri =404;
		}

		location = /healthz {
			proxy_set_header Host \$host;
			proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
			proxy_set_header X-Forwarded-Proto https;
			proxy_pass http://django_backend;
		}

		location / {
			proxy_set_header Host \$host;
			proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
			proxy_set_header X-Forwarded-Proto https;
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
			proxy_pass http://django_backend;
		}
	}
"
else
	echo "==> Disabling SSL in Nginx"
	export ENC_HTTP_REDIRECT=""
	export ENC_SSL_SERVER=""
fi

cd /code/encapsule

# shellcheck disable=SC2016 # variables here are like a docstring for envsubst
envsubst '${ENCAPSULE_PORT} ${ENC_VIEWER_AUTH} ${ENC_HTTP_REDIRECT} ${ENC_SSL_SERVER}' </root/.templates/nginx.conf.template >/etc/nginx/nginx.conf

# Minimal supervision without supervisord: if one service exits, stop the other.
/usr/local/bin/encapsule.sh &
ENCAPSULE_PID=$!

/usr/local/bin/nginx.sh &
NGINX_PID=$!

cleanup() {
	kill -TERM "$ENCAPSULE_PID" "$NGINX_PID" 2>/dev/null || true
}

trap cleanup TERM INT

wait -n "$ENCAPSULE_PID" "$NGINX_PID"
EXIT_CODE=$?

echo "==> One service exited, shutting down the other..."
cleanup
wait "$ENCAPSULE_PID" "$NGINX_PID" 2>/dev/null || true
exit "$EXIT_CODE"
