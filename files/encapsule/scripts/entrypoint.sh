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

cd /code/encapsule

# shellcheck disable=SC2016 # variables are like a docstring for envsubst
envsubst '${ENCAPSULE_PORT} ${ENC_VIEWER_AUTH}' </root/.templates/nginx.conf.template >/etc/nginx/nginx.conf

exec /usr/bin/supervisord --configuration /etc/supervisor/supervisord.conf
