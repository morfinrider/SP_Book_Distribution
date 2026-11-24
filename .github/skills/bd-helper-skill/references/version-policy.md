# Changelog and version policy

1. Inspect the project's changelog format, version source, release documentation, and release scripts before deciding whether to bump a version.
2. Follow the repository's established policy and prefer its release script when that script correctly handles the changelog. Review the output and diff.
3. For semantic versioning, use a patch bump for a backward-compatible bug fix, a minor bump for a backward-compatible feature, and a major bump for a breaking change. Do not bump for documentation-only, test-only, or internal changes unless repository policy requires it.
4. Do not bump again if the current changes already contain the required version.
5. Keep not-yet-shipped work under an existing Unreleased heading. A branch push is not proof of deployment or release.
6. When the user confirms a release, move only the shipped entries into a dated version section. Preserve other unreleased entries and historical notes.
7. Confirm the application still reads the newest numbered version after editing.

If the repository has no version policy or release state is uncertain, do not invent one. Ask the user or leave version metadata unchanged with a clear explanation.
