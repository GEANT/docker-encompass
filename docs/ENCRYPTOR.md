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
