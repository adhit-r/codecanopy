# Releasing CodeCanopy

Keep releases small, reproducible, and honest about what is locally verified.

## Before a release

From a clean checkout, run:

```bash
python3 /Users/adhi/.codex/skills/.system/skill-creator/scripts/quick_validate.py plugins/code-canopy/skills/code-canopy
python3 /Users/adhi/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py plugins/code-canopy
python3 -m unittest discover -s tests -v
python3 benchmarks/model_routing.py
git diff --check
```

The absolute validator paths are for the local Codex installation. CI runs the
repository-owned tests, benchmark, metadata checks, Pages smoke check, and
whitespace check.

## Version and tag

1. Update `plugins/code-canopy/.codex-plugin/plugin.json` and `CHANGELOG.md`.
2. Confirm the README, product metadata, and Pages copy agree about shipped
   capability and evidence tier.
3. Create an immutable tag such as `v0.4.0` only after the checks pass.
4. Publish the tag and verify the GitHub Pages workflow before announcing the
   release.

The current marketplace source tracks `main`, so a tag-pinned installation is
not claimed until the marketplace supports a pinned source and a clean install
smoke test passes. Runtime packaging is a separate release gate because the
current marketplace entry contains the plugin directory, while the local
Python runtime remains at repository root.

## After publishing

```bash
codex plugin marketplace upgrade codecanopy
codex plugin add code-canopy@codecanopy --enable
codex plugin list
```

Restart Codex or start a new task, then verify the installed plugin version and
the public Pages URL. Marketplace refresh alone does not install a new plugin.
