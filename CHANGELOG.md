## [0.9.8] - 2026-03-13

### 🚀 Features

- Feat: add puppet-enc Go binary and update documentation
- Feat: move LDAP logging configuration to UI

### 🐛 Bug Fixes

- Fix: update code formatting to solve linting issues
## [0.9.7] - 2026-03-13

### 🚀 Features

- Feat(ui): clarify default fallback classification and hide hosts in default group
- Feat(auth): enforce MySQL authentication, and leave LDAP optional
- Feat: add global settings card for the admin
- Feat(ui): move tru false settings to MySQL
- Feat: implement optimistic concurrency control for host and group updates
- Feat(tests): ban the superuser from editing profiles as this is a shared account
- Feat: move Puppet environments to Global Settings with DB-backed default and list editor
- Feat: move LDAP/PuppetDB/enCapsule config to Global Settings with test actions and stricter runtime validation
- Feat: add PuppetDB auth and TLS settings to runtime configuration and UI
- Feat: add SSL support for enCapsule with configurable certificate paths and ports

### 🐛 Bug Fixes

- Fix: correct URL path in curl_enc function for ENC node retrieval
- Fix: correct variable names for SSL certificate paths in entrypoint.sh

### 📚 Documentation

- Docs: replace mermaid flowchart with architecture diagram in README
- Doc: mention OpenVox

### ⚙️ Miscellaneous Tasks

- Chore: remove outdated CHANGELOG.md file
## [0.9.6] - 2026-03-09

### 🚀 Features

- Feat: enhance environment input with feedback and suggestions in group and host forms

### 🚜 Refactor

- Refactor: streamline Dockerfile dependencies and improve entrypoint scripts for encapsule and encompass

### 📚 Documentation

- Docs: add ToDo section with cleanup and UI suggestions
- Docs: add mermaid diagram
- Docs: update mermaid diagram for clarity and consistency
- Docs: update preface to clarify Copilot's role in frontend development
- Doc: add presentation on site.pp vs enCompass ENC and its operational benefits

### ⚙️ Miscellaneous Tasks

- Chore(release): update changelog for 0.9.6
## [0.9.5] - 2026-03-08

### 🚀 Features

- Feat: Add Terraform encryptor example and remove old entrypoint script

- Introduced a new Terraform configuration file `terraform-encryptor.tf` for generating CSR attributes on target nodes.
- Removed the obsolete `encapsule-entrypoint.sh` script.
- Added Nginx configuration templates for both enCapsule and encompass services.
- Created new scripts for encapsule and encompass services to manage their respective server processes.
- Implemented Git setup and pull scripts for managing repository synchronization.
- Configured supervisord for managing service processes, including Nginx and application servers.
- Updated requirements for both encapsule and encompass services to include necessary dependencies.

### 🐛 Bug Fixes

- Fix(ci): update artifact build process to include UPX compression for encryptor
- Fix: do not use upx with darwin binaries
- Fix: improve error handling and formatting in push-artifacts and push-containers scripts

### ⚙️ Miscellaneous Tasks

- Chore(release): update changelog for 0.9.5
- Chore(release): update changelog for 0.9.5
- Chore: enable debug mode in push-artifacts script
- Chore(release): update changelog for 0.9.5
- Chore: enable debug mode in push-artifacts script
- Chore(release): update changelog for 0.9.5
- Chore: remove debug mode and fix string comparison in push-artifacts script
- Chore(release): update changelog for 0.9.5
- Chore: enable debug mode in push-artifacts script
- Chore(release): update changelog for 0.9.5
- Chore(release): update changelog for 0.9.5
## [0.9.4] - 2026-03-07

### 🚀 Features

- Feat(ssh): enhance SSH configuration and key handling in git-setup.sh, update vars.example for clarity
- Feat(settings): add ENC_OVERLAPPING_DEFINITIONS_ENABLED setting and validation
- Feat(csr): Add CSR challengePassword management and API endpoints

- Introduced `csr_attributes` module for managing encrypted CSR challengePassword values.
- Added new API endpoints to retrieve CSR attributes for hosts and groups, requiring an API key for access.
- Implemented `enCryptor` binary for fetching CSR challengePassword attributes.
- Updated documentation to reflect new endpoints and usage of `enCryptor`.
- Created management command to rotate CSR challengePassword values for specified entities.
- Enhanced tests to cover new functionality and ensure proper behavior of CSR attribute management.
- Updated requirements to include necessary cryptography library.
- Feat(ci): integrate Codeberg support for Docker image uploads and release asset management
- Feat(docs): add deCryptor documentation and update README for clarity

### 🐛 Bug Fixes

- Fix(ci): add GOTOOLCHAIN variable
- Fix(ci): fix release artifcats creation
- Fix(ci): use external scripts
- Fix(ci): correct remote base URLs for Docker image tagging and pushing
- Fix(ci): test lower case owner with artifacts
- Fix(ci): pass "true" to push-artifacts-codeberg.sh for artifact deletion

### 🚜 Refactor

- Refactor: remove deprecated autosign policy scripts

### 📚 Documentation

- Doc(enc): update README to clarify ENC endpoints and add enCapsule details

### 🎨 Styling

- Style(linter): make linter happy
- Style(linter): make linter happier

### ⚙️ Miscellaneous Tasks

- Chore(release): update changelog for 0.9.4
- Chore(release): update changelog for 0.9.4
- Chore(release): update changelog for 0.9.4
- Chore(release): update changelog for 0.9.4
- Chore(release): update changelog for 0.9.4
- Chore(release): update changelog for 0.9.4
- Chore(release): update changelog for 0.9.4
- Chore(release): update changelog for 0.9.4
## [0.9.3] - 2026-03-02

### 🚀 Features

- Feat(chore): split django code for encapsule and encompass
- Feat(git): implement pull-only sync with git-pull.sh and update git-setup.sh logic
- Feat(docker): update Dockerfile description and requirements for enCapsule; adjust nginx wait time

### ⚙️ Miscellaneous Tasks

- Chore(release): update changelog for 0.9.3
## [0.9.2] - 2026-03-01

### 📚 Documentation

- Doc(migration): clarify ordering and implications of site.pp and ENC in OpenVox/Puppet

### ⚙️ Miscellaneous Tasks

- Chore(release): update changelog for 0.9.2
## [0.9.1] - 2026-03-01

### 🚀 Features

- Feat(docs): add migration notes and comparison between site.pp and enCompass ENC
- Feat(ci): try deleting an image before pushing

### ⚙️ Miscellaneous Tasks

- Chore(release): update changelog for 0.9.1
## [0.9.0] - 2026-03-01

### 🚀 Features

- Feat(logs): improve logging
- Feat(enc): forbid empty host in groups
- Feat(environments): addd feature branch inventory card when FEATURE_BRANCH=true
- Feat(ldap): add warn message if the password expired

### 📚 Documentation

- Doc: add ToDo top implement Kerberos/LDAP password change support

### ⚙️ Miscellaneous Tasks

- Chore(docker): split Dockerfile to make encapsule much smaller
## [0.7.4] - 2026-02-28

### 📚 Documentation

- Doc: update screenshot
## [0.7.3] - 2026-02-28

### 🚀 Features

- Feat(ui): add Spring Cleaning page and home card

add /encompass/spring_cleaning/ route and view
render orphan hosts/groups report
add dashboard card linking to the new page

### 📚 Documentation

- Doc: add SEO message to index the repo in the search engines

### ⚙️ Miscellaneous Tasks

- Chore(release): update changelog for 0.7.3
## [0.7.2] - 2026-02-27

### 💼 Other

- Add validation guardrails for group host selectors to prevent overlaps

### 📚 Documentation

- Doc: added CHANGELOG.md and git-cliff configuration
- Doc: added changelog page to navbar
## [0.7.1] - 2026-02-27

### 💼 Other

- Add popover info concerning regexe
## [0.7.0] - 2026-02-27

### 💼 Other

- Add sync button adn unclassified hosts
- Add test
- Make linter happier
- Update screenshot
## [0.6.3] - 2026-02-25

### 🚀 Features

- Feat: update README with repository URL and add unclassified nodes to ToDo
## [0.6.2] - 2026-02-24

### 🐛 Bug Fixes

- Fix markdown link for the screenshot

### 💼 Other

- Add tags for social media, added encapsule to CI
## [0.6.1] - 2026-02-24

### 🚀 Features

- Feat: add enCapsule documentation; enhance README and Nomad job configuration
## [0.6.0] - 2026-02-24

### 🚀 Features

- Feat: enhance README with HA considerations; add ENC data file; update git setup for SSH config
- Feat: update README and add image; enhance form submission handling in templates

### 🐛 Bug Fixes

- Fix: update README for clarity; rename Data Persistence to Data Backup and improve instructions

### 💼 Other

- Update LICENSE link in README for direct access
- Remove DNS configuration from docker-compose.yml
- Added screenshot
- Add git commits and created encapsule

### 🚜 Refactor

- Refactor README and DEVELOPMENT docs for clarity; update Nomad job description and add GIT_COMMIT variable for save functionality
## [0.5.6] - 2026-02-22

### 💼 Other

- Add demo site link to README
- Add restriction to certains functionalities for viewers and demo_mode
- Add conditional group saving functionality based on user permissions
## [0.5.5] - 2026-02-22

### 💼 Other

- Add authentication checks to user group and identity retrieval functions
## [0.5.4] - 2026-02-22

### 💼 Other

- Update login page background position for demo mode
## [0.5.3] - 2026-02-22

### 💼 Other

- Add demo mode feature and allow only superuser in DB mode to access admin page
## [0.5.2] - 2026-02-22

### 💼 Other

- Normalize static file permissions to resolve Nginx errors
## [0.5.1] - 2026-02-22

### 💼 Other

- Allow reading the private key from a file or from env
## [0.5.0] - 2026-02-21

### 💼 Other

- Initial commit
- Enhance groups page  search functionality
- Add flask app to serve static files
- Replaced HAProxy with Nginx and migrated Flask code to Django
- Switched to mysql
- Removed stale files
- Remove CI creation note from README
- Switch to artifactory
