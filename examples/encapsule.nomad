# Nomad jobs for enCapsule
#
variables {
  nomad_env       = "place-holder"
  url_prefix_env  = "place-holder"
  version         = "place-holder"
  encapsule_count = 0
}

job "encapsule" {
  name        = "${var.nomad_env}-encapsule"
  region      = "global"
  datacenters = ["${var.url_prefix_env}example"]
  type        = "service"

  group "encapsule" {
    vault {
      policies    = ["nomad-server"]
      change_mode = "restart"
    }

    constraint {
      attribute = meta.agent_location
      operator  = "="
      value     = "superpop"
    }

    update {
      max_parallel = 1
      stagger      = "120s"
    }

    vault {
      policies    = ["nomad-server"]
      change_mode = "restart"
    }

    constraint {
      operator = "distinct_hosts"
      value    = "true"
    }

    network {
      port "encapsule" {
        to = 8081
      }
    }

    task "encapsule" {
      driver = "docker"
      env {
        LANGUAGE_CODE            = "en-us"
        TIME_ZONE                = "UTC"
        ALLOWED_HOSTS            = "[\".example.org\", \".example.net\"]"
        GIT_HOST                 = "prod-git01.example.org"
        GIT_BRANCH               = "${var.nomad_env}"
        GIT_REPO_PATH            = "puppet/enc-data.git"
        GIT_REPO_USERNAME        = "gitlab"
        GIT_SSH_KEY_TYPE         = "ed25519" # rsa, ed25519, ecdsa, etc.
        GIT_SSH_PRIVATE_KEY_FILE = "/secrets/git_ssh_private_key_file"
      }

      template {
        perms       = "0600"
        destination = "secrets/git_ssh_private_key_file"
        data        = "{{ with secret \"nomad/common/encompass/git_ssh_private_key_file\" }}{{ .Data.data.value }}{{ end }}"
      }

      template {
        perms       = "0600"
        destination = "secrets/vars"
        data        = "{{ with secret \"nomad/${var.nomad_env}/encompass/vars\" }}{{ .Data.data.value }}{{ end }}"
        env         = true
      }

      template {
        perms       = "0600"
        destination = "secrets/sync_token"
        data        = <<EOF
ENCAPSULE_SYNC_TOKEN={{ with secret "nomad/${var.nomad_env}/encompass/sync_token" }}{{ .Data.data.value }}{{ end }}
EOF
        env         = true
      }

      service {
        name = "${var.nomad_env}-encapsule"
        port = "encapsule"
        check {
          type     = "http"
          port     = "encapsule"
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
        image = "codeberg.org/geant/docker-encompass/encapsule:${var.version}"
        ports = ["encapsule"]
      }

      resources {
        cpu    = 256
        memory = 1024
      }
    }
  }
}
