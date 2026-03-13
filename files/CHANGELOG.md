## [0.9.7] - 2026-03-13

### 🚀 Features

- Feat(logs): improve logging
- Feat(chore): split django code for encapsule and encompass
- Feat(git): implement pull-only sync with git-pull.sh and update git-setup.sh logic
- Feat(docker): update Dockerfile description and requirements for enCapsule; adjust nginx wait time
- Feat(ssh): enhance SSH configuration and key handling in git-setup.sh, update vars.example for clarity
- Feat(csr): Add CSR challengePassword management and API endpoints

- Introduced `csr_attributes` module for managing encrypted CSR challengePassword values.
- Added new API endpoints to retrieve CSR attributes for hosts and groups, requiring an API key for access.
- Implemented `enCryptor` binary for fetching CSR challengePassword attributes.
- Updated documentation to reflect new endpoints and usage of `enCryptor`.
- Created management command to rotate CSR challengePassword values for specified entities.
- Enhanced tests to cover new functionality and ensure proper behavior of CSR attribute management.
- Updated requirements to include necessary cryptography library.
- Feat: Add Terraform encryptor example and remove old entrypoint script

- Introduced a new Terraform configuration file `terraform-encryptor.tf` for generating CSR attributes on target nodes.
- Removed the obsolete `encapsule-entrypoint.sh` script.
- Added Nginx configuration templates for both enCapsule and encompass services.
- Created new scripts for encapsule and encompass services to manage their respective server processes.
- Implemented Git setup and pull scripts for managing repository synchronization.
- Configured supervisord for managing service processes, including Nginx and application servers.
- Updated requirements for both encapsule and encompass services to include necessary dependencies.
- Feat(auth): enforce MySQL authentication, and leave LDAP optional
- Feat: move Puppet environments to Global Settings with DB-backed default and list editor
- Feat: move LDAP/PuppetDB/enCapsule config to Global Settings with test actions and stricter runtime validation
- Feat: add SSL support for enCapsule with configurable certificate paths and ports

### 🐛 Bug Fixes

- Fix(ci): use external scripts
- Fix(ci): correct remote base URLs for Docker image tagging and pushing
- Fix(ci): test lower case owner with artifacts
- Fix(ci): pass "true" to push-artifacts-codeberg.sh for artifact deletion
- Fix(ci): update artifact build process to include UPX compression for encryptor
- Fix: do not use upx with darwin binaries
- Fix: improve error handling and formatting in push-artifacts and push-containers scripts

### 💼 Other

- Add sync button adn unclassified hosts

### 🚜 Refactor

- Refactor: streamline Dockerfile dependencies and improve entrypoint scripts for encapsule and encompass

### ⚙️ Miscellaneous Tasks

- Chore(docker): split Dockerfile to make encapsule much smaller
- Chore: enable debug mode in push-artifacts script
- Chore: enable debug mode in push-artifacts script
- Chore: remove debug mode and fix string comparison in push-artifacts script
- Chore: enable debug mode in push-artifacts script
## [0.6.2] - 2026-02-24

### 🚀 Features

- Feat: enhance README with HA considerations; add ENC data file; update git setup for SSH config

### 💼 Other

- Add restriction to certains functionalities for viewers and demo_mode
- Add git commits and created encapsule
- Add tags for social media, added encapsule to CI
## [0.5.2] - 2026-02-22

### 💼 Other

- Normalize static file permissions to resolve Nginx errors
## [0.5.1] - 2026-02-22

### 💼 Other

- Initial commit
- Add flask app to serve static files
- Replaced HAProxy with Nginx and migrated Flask code to Django
- Switched to mysql
- Removed stale files
- Allow reading the private key from a file or from env
