## [0.9.4] - 2026-03-06

### 🚀 Features

- Feat(csr): Add CSR challengePassword management and API endpoints

- Introduced `csr_attributes` module for managing encrypted CSR challengePassword values.
- Added new API endpoints to retrieve CSR attributes for hosts and groups, requiring an API key for access.
- Implemented `enCryptor` binary for fetching CSR challengePassword attributes.
- Updated documentation to reflect new endpoints and usage of `enCryptor`.
- Created management command to rotate CSR challengePassword values for specified entities.
- Enhanced tests to cover new functionality and ensure proper behavior of CSR attribute management.
- Updated requirements to include necessary cryptography library.

### 💼 Other

- Add sync button adn unclassified hosts

### 🚜 Refactor

- Refactor: remove deprecated autosign policy scripts
## [0.6.1] - 2026-02-24

### 🚀 Features

- Feat: add enCapsule documentation; enhance README and Nomad job configuration

### 💼 Other

- Add restriction to certains functionalities for viewers and demo_mode

### 🚜 Refactor

- Refactor README and DEVELOPMENT docs for clarity; update Nomad job description and add GIT_COMMIT variable for save functionality
