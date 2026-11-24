# Documentation and validation checklist

## README review

- Read the whole README, not only the section related to the current code change.
- Check feature descriptions against current UI, services, configuration, and tests.
- Clearly distinguish local behavior from hosted behavior, including storage durability, access controls, and network requirements.
- Keep setup commands, filenames, settings, date behavior, integrations, and data sources accurate.
- Avoid leaking credentials, personal information, internal paths, or private deployment details.

## Validation

- Find the repository's existing test and check commands; do not add tooling just to validate documentation.
- Run the smallest relevant test after a focused update, and the full suite when the change affects multiple components or a release.
- Report the exact commands and pass/fail results. Do not describe a proposed or skipped check as completed.
- Documentation-only changes need no tests unless the repository has documentation tests.

## Reporting

- Summarize changed documentation, version decisions, validation results, and anything that still needs a deploy or Git operation.
- Never stage, commit, rebase, push, or say a change has been deployed.
