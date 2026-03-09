terraform {
  required_version = ">= 1.3.0"

  required_providers {
    null = {
      source  = "hashicorp/null"
      version = ">= 3.2.1"
    }
  }
}

# Example 2:
# - fetch csr_attributes.yaml directly with curl on the target node
# - install it at the Puppet default location

variable "node_name" {
  description = "Certname/node used in the API path"
  type        = string
}

variable "enc_host" {
  description = "enCapsule/enCompass hostname"
  type        = string
}

variable "csr_api_key" {
  description = "API token used for X-CSR-API-KEY"
  type        = string
  sensitive   = true
}

variable "enc_port" {
  description = "enCapsule/enCompass API port"
  type        = number
  default     = 8081
}

variable "target_host" {
  description = "Target VM IP/DNS for SSH"
  type        = string
}

variable "ssh_user" {
  description = "SSH username for target VM"
  type        = string
}

variable "ssh_private_key_path" {
  description = "Path to private key for SSH"
  type        = string
}

variable "remote_csr_file" {
  description = "Destination path of csr_attributes.yaml on the target node"
  type        = string
  default     = "/etc/puppetlabs/puppet/csr_attributes.yaml"
}

locals {
  csr_api_key_shell = replace(var.csr_api_key, "'", "'\"'\"'")
}

resource "openstack_compute_instance_v2" "my_server" {
  name            = "my_instance"
  image_id        = "55c38903-d2b0-469e-943c-97fd6c6001c3"
  flavor_id       = "126ba281-552d-4a27-9562-4a603b821e59"
  security_groups = ["default"]
  network {
    name = "my_network"
  }

  provisioner "remote-exec" {
    inline = [
      "set -euo pipefail",
      "curl -fsSL -H 'X-CSR-API-KEY: ${local.csr_api_key_shell}' -o /tmp/csr_attributes.yaml http://${var.enc_host}:${var.enc_port}/hosts/${var.node_name}/csr_attributes",
      "test -d \"$(dirname '${var.remote_csr_file}')\" || sudo install -d -m 0755 \"$(dirname '${var.remote_csr_file}')\"",
      "sudo install -m 0600 /tmp/csr_attributes.yaml '${var.remote_csr_file}'",
      "rm -f /tmp/csr_attributes.yaml"
    ]

    connection {
      type        = "ssh"
      host        = var.target_host
      user        = var.ssh_user
      private_key = file(var.ssh_private_key_path)
    }
  }
}
