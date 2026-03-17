# Nomad jobs for encompass
#
job "encompass" {
  region      = "global"
  datacenters = ["example"]
  type        = "service"

  group "encompass" {
    vault {
      policies    = ["nomad-server"]
      change_mode = "restart"
    }

    network {
      port "encompass" {
        to = 8080
      }
      port "enc" {
        to = 8081
      }
    }

    task "encompass" {
      driver = "docker"
      env {
        DEMO_MODE            = true
        USE_ENCAPSULE        = false
        LANGUAGE_CODE        = "en-us"
        TIME_ZONE            = "UTC"
        ALLOWED_HOSTS        = "[\".example.org\", \".example.net\"]"
        ALLOWED_CIDR_NETS    = "[\"192.168.10.0/24\"]"
        CSRF_TRUSTED_ORIGINS = "[\"https://encompass.example.org\", \"https://*.int.example.org\"]"
        CORS_ALLOWED_ORIGINS = "[\"https://encompass.example.org\", \"https://encompass.int.example.org\"]"
        # true/false variables
        DEBUG             = true
        # NGINX variables
        ENC_VIEWER_PASSWORD = ""
        ENC_USE_SSL         = false
        ENC_SSL_CERT_PATH   = ""
        ENC_SSL_KEY_PATH    = ""
        # database variables
        MYSQL_NODES = "haproxy-mariadb.service.consul"
        MYSQL_PORT  = 3306
        MYSQL_DB    = "enc_demo"
        MYSQL_USER  = "enc_demo"
        # Git repository variables
        GIT_HOST                 = "prod-git01.example.org"
        GIT_BRANCH               = "main"
        GIT_REPO_PATH            = "puppet/enc-data.git"
        GIT_REPO_USERNAME        = "gitlab"
        GIT_SSH_KEY_TYPE         = "ed25519"
        GIT_SSH_PRIVATE_KEY_FILE = "/secrets/git_repo_private_ssh_key"
      }

      template {
        perms       = "0600"
        destination = "secrets/git_repo_private_ssh_key"
        data        = "{{ with secret \"nomad/common/encompass/git_repo_private_ssh_key\" }}{{ .Data.data.value }}{{ end }}"
      }

      template {
        perms       = "0600"
        destination = "secrets/mysql_password"
        data        = <<EOF
MYSQL_PASSWORD={{ with secret "nomad/common/encompass/mysql_password" }}{{ .Data.data.value }}{{ end }}
EOF
        env         = true
      }

      template {
        perms       = "0600"
        destination = "secrets/secret_key"
        data        = <<EOF
DJANGO_SECRET_KEY={{ with secret "nomad/common/encompass/secret_key" }}{{ .Data.data.value }}{{ end }}
EOF
        env         = true
      }

      service {
        name = "encompass"
        tags = [
          "traefik",
          "traefik.enable=true",
          # HTTP config
          "traefik.http.routers.encompass.entrypoints=web",
          "traefik.http.routers.encompass.rule=Host(`encompass.int.example.org`) || Host(`encompass.example.org`)",
          # TLS config
          "traefik.http.routers.encompass-demo_tls.entrypoints=websecure",
          "traefik.http.routers.encompass-demo_tls.rule=Host(`encompass.int.example.org`) || Host(`encompass.example.org`)",
          "traefik.http.routers.encompass-demo_tls.tls=true",
          # ACME config
          "traefik.http.routers.encompass-demo_tls.tls.certresolver=example_certresolver",
          "traefik.http.routers.encompass-demo_tls.tls.domains[0].main=encompass.int.example.org",
          "traefik.http.routers.encompass-demo_tls.tls.domains[0].sans=encompass.example.org",
        ]
        port = "encompass"
        check {
          type     = "http"
          port     = "encompass"
          path     = "/healthz"
          interval = "5s"
          timeout  = "2s"
          check_restart {
            limit           = 3
            grace           = "60s"
            ignore_warnings = true
          }
        }
      }
      service {
        name = "enc"
        port = "enc"
        check {
          type     = "http"
          port     = "enc"
          path     = "/healthz"
          interval = "5s"
          timeout  = "2s"
          check_restart {
            limit           = 3
            grace           = "60s"
            ignore_warnings = true
          }
        }
      }

      config {
        image = "codeberg.org/geant/docker-encompass/encompass:${var.version}"
        ports = ["encompass", "enc"]
      }
      resources {
        cpu    = 500
        memory = 2048
      }
    }
  }
}
