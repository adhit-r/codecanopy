# Releasing CodeCanopy

Keep releases small, reproducible, and honest about what is locally verified.

## Before a release

From a clean checkout, run:

```bash
python3 -m pip install --disable-pip-version-check -r requirements-dev.txt
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py" plugins/code-canopy/skills/code-canopy
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator/scripts/validate_plugin.py" plugins/code-canopy
python3 -m unittest discover -s tests -v
python3 benchmarks/model_routing.py
git diff --check
```

The validator paths use the configured `CODEX_HOME`, or the default local Codex installation. CI runs the
repository-owned tests, benchmark, metadata checks, Pages smoke check, and
whitespace check.

## Version and tag

1. Update `plugins/code-canopy/.codex-plugin/plugin.json` and `CHANGELOG.md`.
2. Confirm the README, product metadata, and Pages copy agree about shipped
   capability and evidence tier.
3. Create an immutable tag such as `v0.5.0` only after the checks pass.
4. Publish the tag and verify the GitHub Pages workflow before announcing the
   release.

The rolling marketplace source tracks `main`. A release may also publish a
tag-pinned clean-install command using `--ref vX.Y.Z`, but only after that exact
tag passes a clean marketplace install smoke test. Runtime packaging is a
separate release gate because the current marketplace entry contains the plugin
directory, while the local Python runtime remains at repository root.

## After publishing

```bash
codex plugin marketplace upgrade codecanopy
codex plugin add code-canopy@codecanopy
codex plugin list
```

Restart Codex or start a new task, then verify the installed plugin version and
the public Pages URL. Marketplace refresh alone does not reinstall a plugin,
and repository maintainers cannot remotely force an installed copy to update.
