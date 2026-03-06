# enCapsule

`enCapsule` is the stateless read-only ENC agent runtime for enCompass.  
It does not depend on database and boots up in just 1 second making it ideal for an autoscaling setup.

- No UI
- No migrations
- No MySQL startup dependency
- Shared ENC logic from `encompass/enc_core`

Endpoints:

- `GET /healthz`
- `GET /hosts`
- `GET /hosts/<fqdn>`
- `GET /hosts/<fqdn>/csr_attributes` (requires header `X-CSR-API-KEY`)
- `GET /groups`
- `GET /groups/<name>`
- `GET /groups/<name>/csr_attributes` (requires header `X-CSR-API-KEY`)
- `POST /sync` (requires `ENCAPSULE_SYNC_TOKEN`)
