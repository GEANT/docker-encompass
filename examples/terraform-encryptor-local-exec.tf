terraform {
  required_version = ">= 1.3.0"

  required_providers {
    null = {
      source  = "hashicorp/null"
      version = ">= 3.2.1"
    }
  }
}

# This example runs encryptor locally (where Terraform runs), then uploads
# csr_attributes.yaml to a target VM over SSH.

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

variable "encryptor_bin" {
  description = "Path to local encryptor binary"
  type        = string
  default     = "./cmd/encryptor/encryptor"
}

variable "enc_port" {
  description = "API port used when srv_mode is false"
  type        = number
  default     = 8081
}

variable "srv_mode" {
  description = "Use SRV discovery instead of static port"
  type        = bool
  default     = false
}

variable "target_host" {
  description = "Target VM IP/DNS for SSH upload"
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

locals {
  # Temp file created on the Terraform runner.
  local_csr_file = "${path.module}/.generated/${var.node_name}-csr_attributes.yaml"

  # Destination usually used by Puppet agent.
  remote_csr_file = "/etc/puppetlabs/puppet/csr_attributes.yaml"

  # Build encryptor arguments as a list.
  encryptor_args = concat(
    [
      var.encryptor_bin,
      "-h", var.enc_host,
      "-t", var.csr_api_key,
      "--node", var.node_name,
      "-o", local.local_csr_file
    ],
    var.srv_mode ? ["--srv"] : ["--port", tostring(var.enc_port)]
  )

  # Quote arguments for POSIX shell safety in local-exec.
  encryptor_cmd = join(" ", [for a in local.encryptor_args : format("'%s'", replace(a, "'", "'\\''"))])
}

resource "null_resource" "generate_and_push_csr_attributes" {
  # Re-run if any relevant input changes.
  triggers = {
    node_name              = var.node_name
    enc_host               = var.enc_host
    enc_port               = tostring(var.enc_port)
    srv_mode               = tostring(var.srv_mode)
    target_host            = var.target_host
    ssh_user               = var.ssh_user
    encryptor_binary_path  = var.encryptor_bin
    ssh_private_key_path   = var.ssh_private_key_path
    # Keep out of state as cleartext where possible; hash is enough for drift.
    csr_api_key_hash       = sha256(var.csr_api_key)
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -euo pipefail
      mkdir -p "${path.module}/.generated"
      ${local.encryptor_cmd}
    EOT
  }

  # Upload from local Terraform machine to remote VM.
  provisioner "file" {
    source      = local.local_csr_file
    destination = "/tmp/csr_attributes.yaml"

    connection {
      type        = "ssh"
      host        = var.target_host
      user        = var.ssh_user
      private_key = file(var.ssh_private_key_path)
    }
  }

  # Move file into final path with sudo and strict permissions.
  provisioner "remote-exec" {
    inline = [
      "set -euo pipefail",
      "sudo install -d -m 0755 /etc/puppetlabs/puppet",
      "sudo install -m 0600 /tmp/csr_attributes.yaml ${local.remote_csr_file}",
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
