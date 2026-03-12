# Nomad jobs for encompass
#
job "encompass-demo" {
  name        = "encompass-demo"
  region      = "global"
  datacenters = ["example"]
  type        = "service"

  group "encompass-demo" {
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

    task "encompass-demo" {
      driver = "docker"
      env {
        DEMO_MODE            = true
        USE_ENCAPSULE        = false
        LANGUAGE_CODE        = "en-us"
        TIME_ZONE            = "UTC"
        ALLOWED_HOSTS        = "[\".example.org\", \"localhost\", \"127.0.0.1\"]"
        ALLOWED_CIDR_NETS    = "[\"192.168.10.0/24\"]"
        CSRF_TRUSTED_ORIGINS = "[\"https://encompass-demo.example.org\", \"https://*.int.example.org\", \"https://127.0.0.1\"]"
        CORS_ALLOWED_ORIGINS = "[\"https://encompass-demo.example.org\", \"https://encompass-demo.int.example.org\"]"
        SECRET_KEY           = "7544786B-4CB2-4B78-A799-3963D53DAFC5"
        # true/false variables
        AUTH_LDAP_ENABLED  = false
        DEBUG              = true
        LDAP_AUTH_DEBUG    = false
        # NGINX variables
        ENC_VIEWER_PASSWORD = ""
        USE_SSL             = false
        SSL_CERT_PATH       = ""
        SSL_KEY_PATH        = ""
        # database variables
        MYSQL_HOST                    = "haproxy-mariadb.service.consul"
        MYSQL_PORT                    = 3306
        MYSQL_DB                      = "enc_demo"
        MYSQL_USER                    = "enc_demo"
        ENC_BOOTSTRAP_ADMIN_PASSWORD  = ""
        ENC_BOOTSTRAP_VIEWER_PASSWORD = ""
        # Git repository variables
        GIT_HOST                      = "prod-git01.example.net"
        GIT_REPO_PATH                 = "puppet/enc-data.git"
        GIT_REPO_USERNAME             = "gitlab"
        GIT_BRANCH                    = "main"
        GIT_SYNC_MODE                 = sync
        GIT_SYNC_TIMEOUT              = 30
        GIT_SYNC_RETRIES              = 2
        GIT_SYNC_RETRY_DELAY          = 2
        SSH_KEY_TYPE                  = "ed25519"
        GIT_REPO                      = "ssh://gitlab@prod-git01.example.net/puppet/enc-data.git"
        GIT_REPO_PRIVATE_SSH_KEY_FILE = "/secrets/git_repo_private_ssh_key"
        KEY_FILE                      = "/root/.ssh/id_ed25519"
        FEATURE_BRANCH                = false
        PUPPET_ENVIRONMENTS           = "[\"test\", \"uat\", \"production\"]"
      }

      template {
        perms       = "0600"
        destination = "secrets/git_repo_private_ssh_key"
        data        = "{{ with secret \"nomad/common/encompass-demo/git_repo_private_ssh_key\" }}{{ .Data.data.value }}{{ end }}"
      }

      template {
        perms       = "0600"
        destination = "secrets/mysql_password"
        data        = <<EOF
MYSQL_PASSWORD={{ with secret "nomad/common/encompass-demo/mysql_password" }}{{ .Data.data.value }}{{ end }}
EOF
        env         = true
      }

      template {
        perms       = "0600"
        destination = "secrets/secret_key"
        data        = <<EOF
SECRET_KEY={{ with secret "nomad/common/encompass-demo/secret_key" }}{{ .Data.data.value }}{{ end }}
EOF
        env         = true
      }

      service {
        name = "encompass-demo"
        tags = [
          "traefik",
          "traefik.enable=true",
          # HTTP config
          "traefik.http.routers.encompass-demo.entrypoints=web",
          "traefik.http.routers.encompass-demo.rule=Host(`encompass-demo.int.example.org`) || Host(`encompass-demo.example.org`)",
          # TLS config
          "traefik.http.routers.encompass-demo_tls.entrypoints=websecure",
          "traefik.http.routers.encompass-demo_tls.rule=Host(`encompass-demo.int.example.org`) || Host(`encompass-demo.example.org`)",
          "traefik.http.routers.encompass-demo_tls.tls=true",
          # ACME config
          "traefik.http.routers.encompass-demo_tls.tls.certresolver=example_certresolver",
          "traefik.http.routers.encompass-demo_tls.tls.domains[0].main=encompass-demo.int.example.org",
          "traefik.http.routers.encompass-demo_tls.tls.domains[0].sans=encompass-demo.example.org",
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
        name = "enc-demo"
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
        image = "artifactory.software.geant.org/geant-devops-docker/encompass:latest"
        ports = ["encompass", "enc"]
      }
      resources {
        cpu    = 500
        memory = 2048
      }
    }
  }
}
