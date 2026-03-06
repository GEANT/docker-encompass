## [unreleased]

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

### 📚 Documentation

- Doc(enc): update README to clarify ENC endpoints and add enCapsule details

### 🎨 Styling

- Style(linter): make linter happy
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
