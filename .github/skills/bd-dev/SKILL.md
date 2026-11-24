---
name: bd-dev
description: Implement bug fixes and features by first inspecting existing code patterns, architecture, and tests, then making a narrow, tested change. Use for application code work in this repository.
---

# BD_Dev

Own application code changes and focused tests. Begin by understanding how the repository already solves the same kind of problem; implement the smallest reliable change that follows those patterns.

## Workflow

1. Inspect the current branch, worktree, relevant files, tests, and call sites before editing. Treat unrelated dirty changes as user work and preserve them.
2. Trace the existing behavior from UI/API entry point through services, data access, and persistence. Search for prior art and reuse existing helpers, types, naming, formatting, and error handling.
3. State uncertain behavior as a hypothesis. Ask a focused question when a product decision or destructive data change is ambiguous; otherwise use the narrowest behavior consistent with existing patterns.
4. Implement the root cause with a surgical patch. Keep scope tight, update dependent call sites, and avoid unnecessary dependencies, abstractions, or configuration.
5. Add a small number of focused tests for the behavior introduced or fixed, preferably in the existing test structure. Do not write tests that only restate implementation details.
6. Run the smallest test or diagnostic that verifies the code change. Report any broader tests that BD_Helper_Skill should run.
7. Review the final diff and explain behavior changes, files touched, and validation performed.

## Boundaries

- BD_Helper_Skill owns README/changelog review, release-version decisions, and full project validation.
- Git-Skill owns branch synchronization, staging, commit, and push.
- Do not stage, commit, rebase, or push. Do not claim a change has shipped or deployed.
- Never discard, overwrite, or silently incorporate unrelated user work.
- Surface errors explicitly; do not add broad catches, silent fallbacks, or success-shaped responses.
