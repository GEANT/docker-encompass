terraform {
  required_version = ">= 1.3.0"

  required_providers {
    null = {
      source  = "hashicorp/null"
      version = ">= 3.2.1"
    }
  }
}

# Example 1:
# - download encryptor on the target node
# - make it executable
# - run it to generate csr_attributes.yaml on the target node

variable "node_name" {
  description = "Certname/node passed to encryptor"
  type        = string
}

variable "enc_host" {
  description = "enCompass/enCapsule hostname"
  type        = string
}

variable "csr_api_key" {
  description = "API token used by encryptor"
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
      "curl -fsSL -o /tmp/encryptor https://${var.enc_host}:${var.enc_port}/static/encryptor-linux-amd64",
      "chmod +x /tmp/encryptor",
      "sudo /tmp/encryptor -h '${var.enc_host}' -t '${local.csr_api_key_shell}' --port ${var.enc_port} --node '${var.node_name}' -o '${var.remote_csr_file}'",
      "rm -f /tmp/encryptor"
    ]

    connection {
      type        = "ssh"
      host        = var.target_host
      user        = var.ssh_user
      private_key = file(var.ssh_private_key_path)
    }
  }
}
