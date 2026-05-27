# Changelog

## [0.2.3] - 2026-05-27

### Added — feature parity with streamline-card v0.2.2

- **`!include` tag support** in the templates file. Templates can now be split across multiple files using `!include path/to/template.yaml`. Paths resolve relative to the containing file; nested includes (an included file containing further `!include` directives) are supported. Matches the splitting model documented in [streamline-card v0.2.2](https://github.com/brunosabot/streamline-card/releases/tag/v0.2.2).
- **`element:` template body** for picture-elements use. Templates declaring `element:` instead of `card:` are now expanded into `picture-elements` parent cards. Previously only `card:` was honoured; templates using `element:` were silently passed through unexpanded.
- **Dashboard-local `streamline_templates:` block** at the dashboard config root is now honoured (parity with the upstream README's "Method 2" UI workflow). Templates declared inline in a dashboard merge with the global templates file; dashboard-local templates win on key conflict.
- **Fallback path list** for the global templates file. `streamline_templates_path` (and the `convert_dashboard` argument of the same name) now accepts either a single string or a list of candidate paths. When a list is given, paths are tried in order — the first existing one wins. Matches streamline-card's own primary/fallback location chain (`/config/www/community/streamline-card/...` then `/config/www/streamline-card/...`).

### Added — tests

11 new tests covering: `!include` round-trip, nested `!include`, fallback path resolution (primary wins, all-missing returns None, secondary-when-primary-missing), None path passthrough, `element:` template expansion with variables and defaults, templates lacking both `card` and `element` passing through unchanged, dashboard-local templates expanding correctly, dashboard-local taking precedence on key conflict, and `streamline_templates_path` accepting a fallback list.

## [0.2.2] - 2026-05-20

### Fixed

- String values whose content matches a YAML 1.1 boolean keyword (`on`, `off`, `yes`, `no`, `true`, `false`, `y`, `n`, case-insensitive) are now force-quoted in the converted YAML output. Home Assistant parses YAML files as YAML 1.1, where those bare keywords coerce to booleans on load. Previously, a streamline template carrying `trigger_state: "on"` would emit unquoted `on` after expansion (because `expand_streamline_cards` collapses ruamel.yaml's quote-preserving scalar string types to plain `str` via `copy.deepcopy`), and HA would parse that back as boolean `True` — breaking any consumer doing strict-equality comparison against the string state of a binary_sensor (e.g. Bubble Card's pop-up `trigger_state`). The fix is a custom string representer added to the YAML serialiser; `preserve_quotes=True` alone is insufficient because the deepcopy strips the scalar-type metadata.

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
