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


_YAML_1_1_BOOL_KEYWORDS = frozenset({
    "on", "off", "yes", "no", "true", "false",
    "y", "n",
})


def _quote_yaml11_keywords(representer, data):
    """Force-quote strings whose value is a YAML 1.1 boolean keyword.

    Home Assistant parses YAML files as YAML 1.1, where unquoted ``on``,
    ``off``, ``yes``, ``no``, ``true``, ``false`` (and a few others) become
    booleans, not strings. ruamel.yaml is YAML 1.2 by default and emits these
    values unquoted. The ``expand_streamline_cards`` pipeline collapses
    ruamel ScalarString types to plain ``str`` via ``copy.deepcopy`` + ``dict()``,
    so ``preserve_quotes`` is insufficient on its own.

    Without this representer, a streamline template containing
    ``trigger_state: "on"`` would emit unquoted ``on`` and be parsed back as
    boolean ``True`` — breaking, for example, Bubble Card's strict-equality
    trigger comparison against an entity's "on" string state.
    """
    style = '"' if data.lower() in _YAML_1_1_BOOL_KEYWORDS else None
    return representer.represent_scalar("tag:yaml.org,2002:str", data, style=style)


def _make_yaml() -> ruamel.yaml.YAML:
    y = ruamel.yaml.YAML()
    y.default_flow_style = False
    y.preserve_quotes = True
    y.representer.add_representer(str, _quote_yaml11_keywords)
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


def list_dashboard_urls(storage_dir: str) -> list:
    """Return all dashboard url_paths from the registry, plus None for the default.

    None represents the default dashboard (fixed storage ID "lovelace"), which
    is always present but has no registry entry.  Registered dashboards follow.

    If the registry file is missing or malformed, returns [None] so callers
    still process the default dashboard.
    """
    urls = [None]
    try:
        registry_path = os.path.join(storage_dir, "lovelace_dashboards")
        with open(registry_path, encoding="utf-8") as f:
            data = json.load(f)
        for item in data["data"]["items"]:
            urls.append(item["url_path"])
    except Exception:
        pass
    return urls


def dashboard_uses_streamline(url, storage_dir: str) -> bool:
    """Return True if the dashboard's storage file references custom:streamline-card.

    Uses a raw string search rather than JSON parsing — the type identifier is
    distinctive enough that false positives are not possible in HA storage JSON
    (no comments, entity IDs use dots not colons).

    Returns False on any error (unknown url_path, missing storage file, etc.).
    """
    try:
        dashboard_id = get_lovelace_id_from_url(url, storage_dir)
        storage_path = os.path.join(storage_dir, f"lovelace.{dashboard_id}")
        with open(storage_path, encoding="utf-8") as f:
            return "custom:streamline-card" in f.read()
    except Exception:
        return False


def extract_dashboard_config(json_data: dict) -> dict:
    """Extract the dashboard config from a HA .storage file envelope."""
    return json_data["data"]["config"]


def convert_to_yaml(data: dict) -> str:
    """Convert a dict to a YAML string using ruamel.yaml's OO API."""
    buf = io.StringIO()
    _make_yaml().dump(data, buf)
    return buf.getvalue()


_include_dir_stack: list[str] = []


def _include_constructor(loader, node):
    """Resolve a `!include path` tag. Path is relative to the currently-loading file.

    Reads the active base_dir from `_include_dir_stack` rather than a closure,
    because ruamel.yaml's `add_constructor` registers on a class-level mapping
    shared across YAML instances. The stack is pushed/popped per file load.
    """
    rel = loader.construct_scalar(node)
    base_dir = _include_dir_stack[-1] if _include_dir_stack else ""
    target = os.path.normpath(os.path.join(base_dir, rel))
    target_dir = os.path.dirname(target)
    _include_dir_stack.append(target_dir)
    try:
        with open(target, encoding="utf-8") as f:
            return _make_yaml_with_includes().load(f)
    finally:
        _include_dir_stack.pop()


def _make_yaml_with_includes() -> ruamel.yaml.YAML:
    """Return a ruamel YAML instance that resolves `!include path` tags.

    Paths in `!include` are resolved relative to the file currently being loaded.
    Nested includes are supported (loaded file may itself contain `!include`).
    Matches streamline-card v0.2.2 `!include` semantics (path relative to parent).
    """
    y = _make_yaml()
    y.constructor.add_constructor("!include", _include_constructor)
    return y


def load_streamline_templates(path: str | list[str] | None) -> dict | None:
    """Load streamline templates YAML.

    `path` may be a single string, or a list of candidate paths. When a list is
    given, paths are tried in order; the first existing one wins (matches
    streamline-card's primary + fallback location chain). Returns None if no
    candidate resolves or the file fails to parse.

    Supports `!include` for splitting templates into multiple files (parity with
    streamline-card v0.2.2). Paths in `!include` resolve relative to the
    containing file.
    """
    if path is None:
        return None
    candidates: list[str] = [path] if isinstance(path, str) else list(path)
    for candidate in candidates:
        if not candidate:
            continue
        try:
            base_dir = os.path.dirname(candidate)
            _include_dir_stack.append(base_dir)
            try:
                with open(candidate, encoding="utf-8") as f:
                    return _make_yaml_with_includes().load(f)
            finally:
                _include_dir_stack.pop()
        except FileNotFoundError:
            continue
        except Exception:
            return None
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
        if template_def is None:
            return config

        # Streamline templates declare their body as either `card:` (normal cards)
        # or `element:` (picture-elements). The two are mutually exclusive in a
        # well-formed template; we prefer `card` for compatibility.
        body_key = "card" if "card" in template_def else "element" if "element" in template_def else None
        if body_key is None:
            return config

        defaults = _normalize_variables(template_def.get("default"))
        card_vars = _normalize_variables(config.get("variables"))
        merged = {**defaults, **card_vars}

        expanded = copy.deepcopy(dict(template_def[body_key]))
        expanded = _substitute_variables(expanded, merged)
        return expand_streamline_cards(expanded, templates, _depth + 1)

    return {k: expand_streamline_cards(v, templates, _depth) for k, v in config.items()}


def convert_dashboard(
    url: str | None,
    config_dir: str,
    output_dir: str,
    streamline_templates_path: str | list[str] | None = None,
) -> ConvertResult:
    """Convert a single Lovelace dashboard from JSON storage to YAML.

    Args:
        url: The dashboard url_path (e.g. "office-panel"), or None for default.
        config_dir: Path to the HA config directory (e.g. /config).
        output_dir: Directory to write YAML output files to.
        streamline_templates_path: Path (or list of paths to try in order) for
            the global streamline templates file. Dashboard-local templates
            declared in `streamline_templates:` at the dashboard config root
            are also honoured (matching streamline-card's Method 2) and take
            precedence over the global file on key conflict.

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

    # Merge global + dashboard-local templates. Dashboard-local wins on conflict.
    global_templates = load_streamline_templates(streamline_templates_path) or {}
    dashboard_templates = config.get("streamline_templates")
    if isinstance(dashboard_templates, dict) or global_templates:
        templates = {**global_templates}
        if isinstance(dashboard_templates, dict):
            templates.update(dashboard_templates)
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
