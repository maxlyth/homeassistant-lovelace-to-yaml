"""
Pure Python core logic for converting Lovelace dashboards from JSON to YAML.

No Home Assistant or pyscript dependencies — safe to import in tests.
"""

import copy
import io
import json
import os
import re
from dataclasses import dataclass

import ruamel.yaml

DEFAULT_DASHBOARD_ID = "lovelace"


def _make_yaml() -> ruamel.yaml.YAML:
    y = ruamel.yaml.YAML()
    y.default_flow_style = False
    return y


@dataclass
class ConvertResult:
    success: bool
    dashboard_id: str | None
    output_path: str | None
    error: str | None


def get_lovelace_id_from_url(url: str | None, storage_dir: str) -> str:
    """Return the HA storage ID for a dashboard url_path.

    url=None means the default dashboard, which uses the fixed ID "lovelace".
    Raises ValueError if url_path is not found in the registry.
    """
    if url is None:
        return DEFAULT_DASHBOARD_ID

    registry_path = os.path.join(storage_dir, "lovelace_dashboards")
    with open(registry_path, encoding="utf-8") as f:
        data = json.load(f)

    match = next(
        (x for x in data["data"]["items"] if x["url_path"] == url),
        None,
    )
    if match is None:
        raise ValueError(f"No dashboard found for url_path={url!r}")
    return match["id"]


def extract_dashboard_config(json_data: dict) -> dict:
    """Extract the dashboard config from a HA .storage file envelope."""
    return json_data["data"]["config"]


def convert_to_yaml(data: dict) -> str:
    """Convert a dict to a YAML string using ruamel.yaml's OO API."""
    buf = io.StringIO()
    _make_yaml().dump(data, buf)
    return buf.getvalue()


def load_streamline_templates(path: str) -> dict | None:
    """Load streamline templates YAML. Returns None if file is missing or invalid."""
    try:
        with open(path, encoding="utf-8") as f:
            return _make_yaml().load(f)
    except Exception:
        return None


_MAX_EXPANSION_DEPTH = 10
_VAR_PATTERN = re.compile(r"\[\[(\w+)\]\]")


def _normalize_variables(variables) -> dict:
    """Normalize variable formats to a flat dict.

    Handles both dict format ({"key": "val"}) and array-of-dicts format
    ([{"key": "val"}, {"key2": "val2"}]).
    """
    if not variables:
        return {}
    if isinstance(variables, list):
        merged = {}
        for item in variables:
            if isinstance(item, dict):
                merged.update(item)
        return merged
    if isinstance(variables, dict):
        return dict(variables)
    return {}


def _substitute_variables(obj, variables: dict):
    """Recursively substitute [[var]] placeholders in a data structure."""
    if isinstance(obj, str):
        match = _VAR_PATTERN.fullmatch(obj)
        if match and match.group(1) in variables:
            return variables[match.group(1)]
        return _VAR_PATTERN.sub(
            lambda m: str(variables.get(m.group(1), m.group(0))), obj
        )
    if isinstance(obj, dict):
        return {k: _substitute_variables(v, variables) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute_variables(item, variables) for item in obj]
    return obj


def expand_streamline_cards(config, templates: dict, _depth: int = 0):
    """Recursively expand custom:streamline-card references using templates.

    Returns a new data structure with streamline cards replaced by their
    expanded template content with variables substituted.
    """
    if _depth > _MAX_EXPANSION_DEPTH:
        return config

    if isinstance(config, list):
        return [expand_streamline_cards(item, templates, _depth) for item in config]

    if not isinstance(config, dict):
        return config

    if config.get("type") == "custom:streamline-card" and "template" in config:
        template_name = config["template"]
        template_def = templates.get(template_name)
        if template_def is None or "card" not in template_def:
            return config

        defaults = _normalize_variables(template_def.get("default"))
        card_vars = _normalize_variables(config.get("variables"))
        merged = {**defaults, **card_vars}

        expanded = copy.deepcopy(dict(template_def["card"]))
        expanded = _substitute_variables(expanded, merged)
        return expand_streamline_cards(expanded, templates, _depth + 1)

    return {k: expand_streamline_cards(v, templates, _depth) for k, v in config.items()}


def convert_dashboard(
    url: str | None,
    config_dir: str,
    output_dir: str,
    streamline_templates_path: str | None = None,
) -> ConvertResult:
    """Convert a single Lovelace dashboard from JSON storage to YAML.

    Args:
        url: The dashboard url_path (e.g. "office-panel"), or None for default.
        config_dir: Path to the HA config directory (e.g. /config).
        output_dir: Directory to write YAML output files to.

    Returns:
        ConvertResult describing success or failure.
    """
    storage_dir = os.path.join(config_dir, ".storage")

    try:
        dashboard_id = get_lovelace_id_from_url(url, storage_dir)
    except (ValueError, FileNotFoundError, KeyError) as e:
        return ConvertResult(success=False, dashboard_id=None, output_path=None, error=str(e))

    storage_path = os.path.join(storage_dir, f"lovelace.{dashboard_id}")
    try:
        with open(storage_path, encoding="utf-8") as f:
            json_data = json.load(f)
    except FileNotFoundError as e:
        return ConvertResult(success=False, dashboard_id=dashboard_id, output_path=None, error=str(e))

    config = extract_dashboard_config(json_data)

    if streamline_templates_path:
        templates = load_streamline_templates(streamline_templates_path)
        if templates:
            config = expand_streamline_cards(config, templates)

    yaml_str = convert_to_yaml(config)

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"lovelace_{dashboard_id}.yaml")
    tmp_path = output_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(yaml_str)
    os.replace(tmp_path, output_path)

    return ConvertResult(success=True, dashboard_id=dashboard_id, output_path=output_path, error=None)
