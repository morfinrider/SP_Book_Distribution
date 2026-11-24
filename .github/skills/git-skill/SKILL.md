---
name: git-skill
description: Perform Git operations for the current branch: inspect status and remotes, sync with the latest main, stage reviewed changes, commit, and push. Use when explicitly asked to handle Git or publish the current branch.
---

# Git-Skill

Handle Git operations only. Do not edit application source, README, changelog, or tests; do not decide or change the application version; do not run tests. Preserve all existing work and do not claim a push means deployment.

Read `references/git-safety.md` before operating.

## Workflow

1. Identify the repository root, current branch, worktree status, branch tracking configuration, and all remotes. Inspect tracked diffs and untracked paths before staging anything.
2. Ensure the current branch is not `main` or another protected default branch. If it is, create a descriptive topic branch without losing changes. Never commit or push to a protected branch.
3. Determine which changed paths belong to the requested work. Stage only those reviewed paths by explicit path. If unrelated, sensitive, or unclear changes could be included or prevent a safe rebase, stop and ask how the user wants them preserved.
4. Review the staged diff and status. Commit only the requested, reviewed changes using the repository's commit-message convention.
5. Fetch from the unambiguous base remote and rebase the current branch onto that remote's latest `main`. Preserve the working branch. Resolve only clear, mechanical conflicts; otherwise stop with the rebase state intact and report what needs review.
6. If rebase conflict resolution changed application source or tests, stop before pushing and ask for the relevant validation. Do not run tests yourself.
7. Push the current branch to its configured push remote, setting upstream when it has none. Never push to `main`. Use a normal push first; follow `references/git-safety.md` before any lease-protected push.
8. Verify the remote branch and report the branch, commits, push result, and any remaining worktree changes. State explicitly that deployment was not performed.

## Stop and ask when

- The correct remote or `main` base is ambiguous.
- There are unrelated or unclear changes that cannot safely be left untouched.
- Git authentication, permissions, a protected branch, or a conflict blocks the workflow.
- A push is rejected for a reason that cannot be resolved without rewriting history or discarding another person's commits.
