# Contributing

Thank you for your interest in the Terraform Policy Agent. Bug reports, documentation fixes, ideas and code contributions are all welcome from the community.

## Before you start

- **Security issues:** do not open a public issue. Follow [SECURITY.md](SECURITY.md).
- **Need help using the tool?** Read the [User Guide](USER_GUIDE.md) and [Troubleshooting](TROUBLESHOOTING.md) first.
- **Never include secrets** in issues, pull requests, logs or screenshots: no tokens, API keys, account identifiers, hostnames or personal paths.

## Reporting a bug or requesting a change

1. Search the existing issues to avoid duplicates.
2. Open an issue with the **Bug or Incorrect Behavior** or **Documentation Issue** template.
3. Include the image tag (`IMAGE_TAG`), your operating system, your container engine (Podman or Docker), the provider and model, and the stage where it failed. Add the smallest sanitized input that reproduces the problem.

Conversion quality problems are most useful when they are described in general terms ("Rego `some ... in` rules are dropped") rather than as one customer-specific policy.

## Suggesting or making a change

1. Open an issue first for anything larger than a typo, so we can agree on the approach.
2. Fork the repository and create a branch.
3. Keep the change focused. Update the documentation (`README.md`, `USER_GUIDE.md`) and add a line under `[Unreleased]` in `CHANGELOG.md` when behaviour changes.
4. Check your change: run `./pre-check.sh` and convert the sample policies in `sample-data/input/` (a Sentinel and an OPA/Rego sample) before and after.
5. Sign off your commits (`git commit -s`) to certify that you have the right to submit them, and open a pull request using the pull request template.

### How pull requests are handled

This repository is generated from HashiCorp's internal source repository at release time, so **pull requests opened here cannot be merged directly**: the next release would overwrite the merge. Pull requests are still welcome as a way to propose a change. A maintainer reviews the proposal here, ports an accepted change to the source repository, and it ships with the next release. The change will not appear as your original commit, and this pull request is closed with a link to the release that contains it. We credit contributors in the release notes.

## Licence

Contributions are made under the licence of this repository, the [Mozilla Public License 2.0](LICENSE).
