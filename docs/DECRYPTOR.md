# deCryptor (Optional)

`deCryptor` is an optional Puppet autosign policy helper that validates CSR
`challengePassword` against enCompass/enCapsule.

Component name is `deCryptor`; executable name is `decryptor`.

## Build

```bash
cd cmd/decryptor
go build -o decryptor .
```

## Config

- Default config path: `/etc/puppetlabs/puppet/decryptor.yaml`
- Example config: `examples/decryptor.yaml`
- Token file default: `/etc/puppetlabs/puppet/csr_api_key`

## Usage

```bash
# Puppet passes CSR PEM on stdin and certname as $1
cat /path/to/request.pem | ./decryptor node1.example.org
```

## Exit codes

- `0`: challenge matches, autosign allowed.
- non-zero: reject or error.

## Puppet policy wrapper example

```bash
sudo install -m 0755 examples/autosign-policy-decryptor.sh /etc/puppetlabs/puppet/autosign-policy.sh
```
