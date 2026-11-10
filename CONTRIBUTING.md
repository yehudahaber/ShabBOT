# Contributing

## Development

```bash
uv sync                      # Python 3.14, pinned Home Assistant test harness
uv run pytest -q             # zmanim vs hebcal.com, planner, executor/protection/override flows
cd frontend && npm ci && npm run build   # builds custom_components/shabbot/frontend/shabbot-panel.js
```

Run a throwaway Home Assistant against the working tree:

```bash
uv run hass -c .devha        # .devha/custom_components/shabbot → ../../custom_components/shabbot
```

## Brand images

The integration icon and logo, sidebar icon, panel header icon and README banner are generated from vector shapes:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/usr/local/lib uvx --with cairosvg --with fonttools python assets/build_brand.py
```

## Releases

1. Set the new version in `manifest.json`, `const.py`, `pyproject.toml`, `frontend/package.json` and both lockfiles.
2. Wait for validation to pass on `main`.
3. Publish a GitHub release tagged `vX.Y.Z` and titled `ShabBOT X.Y.Z`. The workflow builds the panel and attaches `shabbot.zip`, which the Marketplace and HACS install.

Write the notes for people running ShabBOT, under `### New`, `### Improvements` or `### Fixes`, and say what changes for them.
