# Changelog

## [0.1.0] - 2026-03-25

Initial release.

### Added

- Automatic conversion of Lovelace dashboards from HA JSON storage (`.storage/lovelace.*`) to readable YAML on every `lovelace_updated` event
- Static expansion of [Streamline Card](https://github.com/brunosabot/streamline-card) templates during conversion — `custom:streamline-card` references are replaced with fully rendered card config, significantly improving dashboard responsiveness on low-compute panels
- `pyscript.lovelace_convert` service for manual on-demand conversion via Developer Tools
- Output filenames derived from dashboard ID (e.g. `lovelace_office_panel.yaml`)
- Output directory created automatically on first write
- HACS-compatible pyscript app with configuration via `pyscript.app_config` in `configuration.yaml`
- Full test suite (unit + integration) runnable with `pytest` — no running HA instance required
- Pyscript mock layer (`pyscript_mock.py`) allowing `__init__.py` to be exercised in CI
- CI testing against Python 3.11 and 3.12
