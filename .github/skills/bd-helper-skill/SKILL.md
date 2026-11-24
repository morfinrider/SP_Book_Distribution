---
name: bd-helper-skill
description: Review and update project documentation, README and changelog/version metadata, then run unit tests and relevant project checks. Use after a code change or when asked to document, release, or validate this project.
---

# BD_Helper_Skill

Handle documentation, release metadata, and validation only. Do not implement application behavior, stage files, create commits, rebase, or push.

Read `references/documentation-checklist.md` and `references/version-policy.md` before working.

## Workflow

1. Inspect the repository's README, changelog, version source, release scripts, tests, and current diff. Ground every documented feature in the implementation.
2. Update the README when user-visible behavior, setup, configuration, deployment, or operational guidance changed. Remove claims that are stale or unsupported; do not publish secrets or private data.
3. Decide whether the changelog and version need updating using `references/version-policy.md`. Keep the app's displayed version consistent with the newest numbered release. Do not claim a change has shipped unless deployment is confirmed.
4. Run the smallest relevant unit tests first. Run the full project test suite when requested or when the release change affects multiple components. Run other existing project checks when applicable.
5. If validation fails, inspect and report the failure. Fix documentation/test configuration issues only when directly caused by this documentation/release task; delegate application code fixes to BD_Dev or ask the user.
6. Review the final README/changelog diff and report updates, version decision, commands and results, and any remaining deployment steps.

## Boundaries

- BD_Dev owns application code changes and focused test additions.
- Git-Skill owns staging, branch synchronization, commits, and pushes.
- This skill may inspect Git status and diffs but must not change the Git index or repository history.
- If release status, version impact, or the intended documentation is ambiguous, ask before inventing policy.
