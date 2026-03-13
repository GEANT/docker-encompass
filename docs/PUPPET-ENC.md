# puppet-enc

`puppet-enc` is an optional Go binary that queries the enCompass/enCapsule ENC
API, suitable as a drop-in replacement for `puppet-enc.sh` on busy Puppet
Servers where the lower process-spawn overhead of a compiled binary matters.

Executable name: `puppet-enc`.  
Source: `cmd/puppet-enc/`.

## Why a compiled binary instead of the shell script?

The shell script (`examples/puppet-enc.sh`) spawns several external processes
per run (`curl`, `dig`, `awk`, `sed`, `shuf`). On a busy Puppet Server with
frequent agent check-ins the resulting CPU pressure and tail latency are
measurable.

Benchmark on localhost (hyperfine, 169/53 runs):

| Command       | Mean    | Min     |
|---------------|---------|---------|
| puppet-enc.sh | 37.3 ms | 27.9 ms |
| puppet-enc    | 13.8 ms | 10.3 ms |

The Go binary is roughly **2–3× faster** and uses **3–4× less CPU time** per
call in a low-latency environment. On higher-latency network paths the relative
gain shrinks but CPU savings remain.

## Build

```bash
cd cmd/puppet-enc
go build -o puppet-enc .
```

Cross-compile for a Linux Puppet Server from macOS:

```bash
GOOS=linux GOARCH=amd64 go build -o puppet-enc .
```

Pre-built binaries for `linux/amd64`, `linux/arm64`, and `darwin/arm64` are
published to the Codeberg package registry on every tag.

## Installation

```bash
sudo install -m 0755 puppet-enc /etc/puppetlabs/puppet/enc/puppet-enc
```

## Usage

```bash
# Static port
puppet-enc --node mynode.example.org --server enc.example.org --port 8081

# SRV record (_puppet8._tcp.<server>) — picks one record at random each run
puppet-enc --node mynode.example.org --server example.org --srv

# Round-robin DNS — tries every A/AAAA address in sequence until one succeeds
puppet-enc --node mynode.example.org --server enc.example.org --rrdns --port 8081

# With basic auth
puppet-enc --node mynode.example.org --server enc.example.org --port 8081 \
  --user apiuser --password apipass

# Short flags are also accepted
puppet-enc -n mynode.example.org -s enc.example.org --port 8081
```

## Flags

| Flag           | Short | Description                                         |
|----------------|-------|-----------------------------------------------------|
| `--node`       | `-n`  | Node to query (required)                            |
| `--server`     | `-s`  | Server hostname/IP (required)                       |
| `--port`       |       | Static port (required unless `--srv`)               |
| `--srv`        |       | Resolve via SRV record `_puppet8._tcp.<server>`     |
| `--rrdns`      |       | Resolve all A/AAAA records and try each in sequence |
| `--user`       | `-u`  | Username for basic auth (requires `--password`)     |
| `--password`   | `-p`  | Password for basic auth (requires `--user`)         |
| `-h`, `--help` |       | Show help                                           |

`--srv` and `--rrdns` are mutually exclusive.  
`--srv` and `--port` are mutually exclusive.

## Nomad / autoscaling note

DNS and SRV lookups are performed on **every invocation** — there is no
connection pooling or caching across runs. This is intentional: it ensures that
autoscaled enCapsule instances registered in Nomad/Consul are always discovered
fresh, with no stale address being used.

Within a single run, when `--rrdns` is used and multiple addresses are tried,
the HTTP connection is reused across retries via a shared `http.Transport`.

## Puppet Server integration

Create a wrapper so Puppet passes the agent certname as `$1`:

```bash
sudo tee /etc/puppetlabs/puppet/enc/enc-wrapper.sh >/dev/null <<'EOF'
#!/usr/bin/env bash
exec /etc/puppetlabs/puppet/enc/puppet-enc \
  --node "$1" \
  --server encompass.example.org \
  --srv
EOF
sudo chmod 0755 /etc/puppetlabs/puppet/enc/enc-wrapper.sh
```

Configure Puppet Server in `/etc/puppetlabs/puppet/puppet.conf`:

```ini
[server]
node_terminus = exec
external_nodes = /etc/puppetlabs/puppet/enc/enc-wrapper.sh
```

Apply and verify:

```bash
sudo systemctl restart puppetserver
sudo puppet config print node_terminus external_nodes --section master
```

## Exit codes

| Code | Meaning                                                    |
|------|------------------------------------------------------------|
| `0`  | Success, valid YAML printed to stdout                      |
| `1`  | Runtime error (connection failure, non-2xx response, etc.) |
| `2`  | Argument error                                             |

## Relation to puppet-enc.sh

`puppet-enc` is a feature-complete drop-in replacement for
[`examples/puppet-enc.sh`](../examples/puppet-enc.sh). Both accept the same
flags and produce identical output. The shell script remains available for
environments where deploying a compiled binary is not practical.
