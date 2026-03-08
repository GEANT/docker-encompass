# enCryptor (Optional)

`enCryptor` is an optional helper binary used to fetch CSR `challengePassword`
attributes from enCompass/enCapsule.

Component name is `enCryptor`; executable name is `encryptor`.

It can be used during provisioning to write the YAML blob consumed by Puppet CSR
attributes workflows.

## Build

```bash
cd cmd/encryptor
go build -o encryptor .
```

## Usage

```bash
./encryptor -h enc.example.org -t "$CSR_API_KEY" --port 8081 --node node1.example.org
./encryptor -h enc.example.org -t "$CSR_API_KEY" --srv --node node1.example.org
./encryptor -h enc.example.org -t "$CSR_API_KEY" --port 8444 --scheme https --insecure --node node1.example.org
./encryptor -h enc.example.org -t "$CSR_API_KEY" --port 8081 --node node1.example.org -o /etc/puppetlabs/puppet/csr_attributes.yaml
```

## Notes

- `-h/--host` and `-t/--token` are required.
- Use either `--port` or `--srv`.
- In non-SRV mode `--port` is mandatory.
- If DNS resolves multiple A/AAAA records, one target is selected per invocation.
- If `--node` is omitted, local hostname is used.
- `-o/--output` writes YAML to a file (default behavior remains stdout).
- Recommended file path: `/etc/puppetlabs/puppet/csr_attributes.yaml`.
- `-k/--insecure` skips TLS certificate verification (use only when needed).

## Output

Example output:

```yaml
---
custom_attributes:
  challengePassword: secure_password
```

## Terraform Patterns (remote-exec)

Terraform examples now use `remote-exec` directly on the target VM.

- Pattern 1: download `encryptor` on the VM, run it, and write
  `csr_attributes.yaml` in place.
  See: [examples/terraform-encryptor.tf](https://codeberg.org/GEANT/docker-encompass/src/branch/main/examples/terraform-encryptor.tf)
- Pattern 2: fetch `csr_attributes.yaml` directly with `curl` from the ENC API,
  then install it at the target path.
  See: [examples/terraform-curl.tf](https://codeberg.org/GEANT/docker-encompass/src/branch/main/examples/terraform-curl.tf)
