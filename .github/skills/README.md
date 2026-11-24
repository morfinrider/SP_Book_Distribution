# Project Copilot skills

These skills are split by responsibility so they can be used independently and moved into a dedicated skills repository later.

| Skill | Responsibility | Example invocation |
|---|---|---|
| `git-skill` (Git-Skill) | Git status, branch and remote checks, syncing with `main`, staging, commit, and push | `Use the /git-skill skill to sync and push this branch.` |
| `bd-helper-skill` (BD_Helper_Skill) | Review/update README and changelog, decide release version, run unit tests and project checks | `Use the /bd-helper-skill skill to update docs and validate this release.` |
| `bd-dev` (BD_Dev) | Inspect existing code patterns and implement a code fix or feature with focused tests | `Use the /bd-dev skill to implement this feature.` |

Recommended workflow for a code change: **BD_Dev → BD_Helper_Skill → Git-Skill**. Git-Skill never changes application code or runs tests; BD_Helper_Skill never stages, commits, or pushes. Keep each skill directory self-contained, including its `references/` folder, when moving it to a separate repository.

Project skills live under `.github/skills/`. Copilot skills use lowercase, hyphenated identifiers even when their display headings use the requested names.
