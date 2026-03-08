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

resource "null_resource" "generate_csr_attributes_remote_exec" {
  triggers = {
    node_name            = var.node_name
    enc_host             = var.enc_host
    enc_port             = tostring(var.enc_port)
    target_host          = var.target_host
    ssh_user             = var.ssh_user
    ssh_private_key_path = var.ssh_private_key_path
    csr_api_key_hash     = sha256(var.csr_api_key)
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
