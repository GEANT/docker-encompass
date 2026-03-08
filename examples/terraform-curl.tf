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

resource "null_resource" "fetch_csr_attributes_with_curl_remote_exec" {
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
