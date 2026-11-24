# Git safety

- Inspect `git status --short`, `git branch -vv`, `git remote -v`, branch tracking settings, and relevant diffs before acting.
- Never use `git add .` or `git add -A`. Stage only explicit, reviewed paths.
- Exclude secrets, environment files, local databases, logs, state files, caches, generated output, and unrelated images unless they are explicitly required.
- Do not reset, clean, restore, amend, or automatically stash unrelated work.
- Prefer the current branch's configured push remote when it also contains the intended `main` base. If multiple remotes are plausible and configuration does not disambiguate them, ask.
- Fetch before rebasing; rebase the topic branch onto `<base-remote>/main`. Never commit or push directly to `main`.
- Push normally first. Never use `git push --force`. Use `--force-with-lease` only after fetching and confirming the remote branch has not advanced beyond the exact history being replaced. If uncertain, stop.
- Verify the final branch and remote state. A push is not a deployment.
