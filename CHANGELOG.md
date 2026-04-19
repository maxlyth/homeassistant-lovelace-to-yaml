# Changelog

## [0.2.1] - 2026-04-19

### Fixed

- Stale-read race: `lovelace_updated` events can fire before HA's `LovelaceStorage` has flushed the new JSON to disk, so the conversion could read the previous saved state and produce a YAML that did not match the final JSON. The event handler now debounces per-`url_path` using `task.unique` + `task.sleep` (default 10s, configurable via `debounce_seconds`). Rapid successive saves collapse into a single conversion.
- `TypeError: lovelace_updated_event() called with unexpected keyword arguments`: the handler now accepts `**kwargs` so additional event-data fields attached by HA or forwarded via `remote_homeassistant` no longer raise.

### Added

- `debounce_seconds` option in `pyscript.app_config` (default 10). Set to your environment's `LovelaceStorage` save delay plus a small margin.

## [0.2.0] - 2026-03-26

### Added

- Automatic reconversion of Streamline dashboards when `streamline_templates.yaml` changes on disk, via HA's `folder_watcher` integration
- Only dashboards that reference `custom:streamline-card` are reconverted — plain dashboards are unaffected
- `closed` event type support so editors that write via temp-file rename (e.g. vim) are detected correctly

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
