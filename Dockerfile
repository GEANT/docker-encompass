# Dockerfile
#
# https://dockerize.io/guides/python-django-guide
#
# The first instruction is what image we want to base our container on
# We Use an official Python runtime as a parent image
FROM python:3.14

LABEL author="Massimiliano Adamo <massimiliano.adamo@geant.org>" \
      description="Encompass is a tool to manage a Puppet ENC with a Django web interface." \
      version="1.0.0"

# Custom cache invalidation: check .gitlab-ci.yml for details
ARG CACHEBUST=1
ARG APP_DEBUG=false

ENV PREFIX="/enc" \
    PYTHONUNBUFFERED=1 \
    PIP_ROOT_USER_ACTION=ignore \
    APP_DEBUG=${APP_DEBUG}

# Instaall all dependencies and cleanup the image, if not in debug mode
COPY requirements.txt /requirements.txt
RUN apt update && \
    apt install -y libsasl2-dev libldap2-dev sqlite3 haproxy gettext-base supervisor netcat-openbsd && \
    pip3 install --root-user-action=ignore --disable-pip-version-check --no-compile --upgrade pip setuptools wheel && \
    pip3 install --root-user-action=ignore --no-compile --requirement /requirements.txt
RUN if [ "$APP_DEBUG" = "true" ]; then \
        apt install -y vim telnet lsof curl; \
    else \
        apt full-upgrade -y; \
        apt-get --purge remove -y libsasl2-dev libldap2-dev; \
        apt clean && \
        rm -rf /root/.cache/pip/* /var/lib/apt/lists/*; \
    fi

COPY files/supervisord /etc/supervisor/conf.d
COPY --chmod=755 files/scripts /usr/local/bin
COPY --chmod=644 files/haproxy.cfg.template /root/haproxy.cfg.template
COPY --chmod=644 files/watermark /local/watermark
COPY --chmod=644 files/version /local/version
COPY --chmod=644 files/bashrc /root/.bashrc
COPY --chmod=644 files/vimrc /root/.vimrc
COPY static code/static/static
COPY --chmod=755 files/enc.py /code/enc/enc.py
COPY --chmod=755 files/static.py /code/static/static.py
COPY encompass code/encompass
RUN ln -s /data /code/enc/data

# port explanations: check docker-compose.yml for details
EXPOSE 8080 8081 8082 8443 8444 8445

# runs the development server in debug mode
WORKDIR /code/encompass
CMD ["/usr/local/bin/entrypoint.sh"]
