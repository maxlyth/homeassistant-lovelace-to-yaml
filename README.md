# homeassistant-lovelace-to-yaml

[![Tests](https://github.com/maxlyth/homeassistant-lovelace-to-yaml/actions/workflows/tests.yml/badge.svg)](https://github.com/maxlyth/homeassistant-lovelace-to-yaml/actions/workflows/tests.yml)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Automatically converts your Home Assistant Lovelace dashboard configurations from JSON to readable YAML whenever you save a dashboard in the UI. The YAML files are easy to read, diff, and commit to version control.

## How it works

Home Assistant stores dashboards as JSON in `.storage/lovelace.*`. This pyscript app listens for the `lovelace_updated` event and writes a clean YAML snapshot to a directory of your choice each time a dashboard is saved.

```
Edit dashboard in HA UI
        ↓
lovelace_updated event fires
        ↓
lovelace_to_yaml reads .storage/lovelace.<id>
        ↓
Extracts data.config, converts to YAML
        ↓
Writes lovelace_<id>.yaml to OUTPUT_DIR
```

## Prerequisites

- [pyscript custom component](https://github.com/custom-components/pyscript) installed via HACS

## Installation

1. Add this repository to HACS as a custom repository (category: **pyscript**)
2. Install **Lovelace to YAML** via HACS
3. Add the configuration block below to `configuration.yaml`
4. Restart Home Assistant

## Configuration

Add to `configuration.yaml`:

```yaml
pyscript:
  allow_all_imports: true
  apps:
    lovelace_to_yaml:
      config_dir: "/config"
      output_dir: "/config/lovelace_yaml"
      streamline_templates_path: "/config/www/community/streamline-card/streamline_templates.yaml"
```

All keys under `lovelace_to_yaml:` are optional — the values above are the defaults.

| Key | Default | Description |
|-----|---------|-------------|
| `config_dir` | `/config` | Path to your HA config directory |
| `output_dir` | `/config/lovelace_yaml` | Directory where YAML files are written |
| `streamline_templates_path` | `/config/www/community/streamline-card/streamline_templates.yaml` | Path to Streamline Card templates (see below) |

### Why `allow_all_imports: true`?

This app imports `ruamel.yaml` (for YAML output), `os`, `copy`, and `io` — standard library and one third-party package. Pyscript restricts imports by default; `allow_all_imports: true` lifts that restriction. This is standard practice for pyscript apps that do file I/O or use third-party libraries. The `ruamel.yaml` dependency is automatically installed by pyscript from the app's `requirements.txt`.

## Output

Each dashboard produces one file named after its internal ID:

| Dashboard | Output file |
|-----------|-------------|
| Default dashboard | `lovelace_lovelace.yaml` |
| `office-panel` | `lovelace_office_panel.yaml` |
| `map` | `lovelace_map.yaml` |

The YAML contains only the dashboard configuration — the HA storage metadata (`version`, `key`, etc.) is stripped.

**Example output** (`lovelace_map.yaml`):
```yaml
views:
- cards:
  - auto_fit: true
    entities:
    - person.example_user
    - zone.home
    type: map
  icon: mdi:map
  title: Map
  type: panel
```

## Manual conversion

You can trigger a conversion without editing a dashboard via **Developer Tools → Actions → `pyscript.lovelace_convert`**.

| Field | Description |
|-------|-------------|
| `url` | URL path of the dashboard (e.g. `office-panel`). Leave empty for the default dashboard. |

## Streamline Card Support

If you use the [Streamline Card](https://github.com/brunosabot/streamline-card) HACS plugin, template references are automatically expanded during conversion. Instead of seeing `custom:streamline-card` stubs in the YAML output, you get the fully expanded card configuration with variables substituted.

### How it works

1. The app loads your `streamline_templates.yaml` file
2. Each `custom:streamline-card` reference is replaced with the template's `card` config
3. `[[variable]]` placeholders are substituted with the card's variable values (falling back to template defaults)
4. Nested templates (templates that reference other templates) are expanded recursively

If the templates file doesn't exist, expansion is silently skipped — the app works fine without Streamline.

### JavaScript keys

Template properties with `_javascript` suffixes (e.g. `service_javascript`, `icon_color_javascript`) are kept in the YAML output with `[[variable]]` placeholders substituted, but they require the Streamline runtime to execute. They appear in the YAML for readability.

## Limitations

- Only works with dashboards in **storage mode**. Dashboards configured via YAML files in `/config/` are not affected.

## Development

```bash
# Clone and install dev dependencies
git clone https://github.com/maxlyth/homeassistant-lovelace-to-yaml
cd homeassistant-lovelace-to-yaml
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=lovelace_core --cov-report=term-missing
```

### Project structure

```
homeassistant-lovelace-to-yaml/
├── pyscript/
│   └── apps/
│       └── lovelace_to_yaml/
│           ├── __init__.py       # pyscript wrapper (event trigger, service)
│           ├── lovelace_core.py  # Pure Python core logic (testable)
│           └── requirements.txt  # ruamel.yaml
├── tests/
│   ├── conftest.py
│   ├── pyscript_mock.py          # Mock pyscript globals for integration tests
│   ├── fixtures/                 # Sample HA .storage files
│   ├── test_core.py              # Unit tests for lovelace_core.py
│   └── test_integration.py       # Integration tests for __init__.py under mocked pyscript
├── hacs.json
└── pyproject.toml
```

`lovelace_core.py` contains all the conversion logic as pure Python with no HA dependency. The pyscript `__init__.py` loads it via `importlib` (bypassing pyscript's async-wrapping module system) and wraps it with pyscript-specific decorators (`@pyscript_executor`, `@event_trigger`, `@service`). Unit tests run against `lovelace_core.py` directly; integration tests exercise `__init__.py` under a mocked pyscript environment — no running HA instance needed for either.

## License

[MIT](LICENSE)
