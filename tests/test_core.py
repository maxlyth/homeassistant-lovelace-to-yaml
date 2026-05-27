"""Tests for src/lovelace_core.py.

Tests assert on observable outputs (return values, file contents, exceptions)
and do not depend on internal implementation details.
"""

import io
import json
import os

import pytest
import ruamel.yaml

from lovelace_core import (
    DEFAULT_DASHBOARD_ID,
    ConvertResult,
    _normalize_variables,
    _substitute_variables,
    convert_dashboard,
    convert_to_yaml,
    dashboard_uses_streamline,
    expand_streamline_cards,
    extract_dashboard_config,
    get_lovelace_id_from_url,
    list_dashboard_urls,
    load_streamline_templates,
)


# ── get_lovelace_id_from_url ──────────────────────────────────────────────────

def test_get_id_none_returns_default_without_reading_files():
    """url=None must return the default ID without touching the filesystem."""
    result = get_lovelace_id_from_url(None, "/nonexistent/path")
    assert result == DEFAULT_DASHBOARD_ID
    assert result == "lovelace"


def test_get_id_known_url_path(config_dir):
    storage_dir = os.path.join(config_dir, ".storage")
    assert get_lovelace_id_from_url("map", storage_dir) == "map"
    assert get_lovelace_id_from_url("office-panel", storage_dir) == "office_panel"


def test_get_id_unknown_url_path_raises(config_dir):
    storage_dir = os.path.join(config_dir, ".storage")
    with pytest.raises(ValueError, match="no-such-dashboard"):
        get_lovelace_id_from_url("no-such-dashboard", storage_dir)


def test_get_id_missing_registry_raises(tmp_path):
    """A missing registry file should raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        get_lovelace_id_from_url("map", str(tmp_path))


# ── list_dashboard_urls ───────────────────────────────────────────────────────

def test_list_dashboard_urls_includes_default_and_registered(config_dir):
    storage_dir = os.path.join(config_dir, ".storage")
    urls = list_dashboard_urls(storage_dir)
    assert None in urls
    assert "map" in urls
    assert "office-panel" in urls
    assert "streamline-dash" in urls


def test_list_dashboard_urls_default_is_first(config_dir):
    storage_dir = os.path.join(config_dir, ".storage")
    urls = list_dashboard_urls(storage_dir)
    assert urls[0] is None


def test_list_dashboard_urls_missing_registry_returns_default_only(tmp_path):
    urls = list_dashboard_urls(str(tmp_path))
    assert urls == [None]


def test_list_dashboard_urls_empty_registry(tmp_path):
    storage = tmp_path / ".storage"
    storage.mkdir()
    (storage / "lovelace_dashboards").write_text(
        '{"version":1,"minor_version":1,"key":"lovelace_dashboards","data":{"items":[]}}',
        encoding="utf-8",
    )
    urls = list_dashboard_urls(str(storage))
    assert urls == [None]


# ── dashboard_uses_streamline ─────────────────────────────────────────────────

def test_dashboard_uses_streamline_true_for_streamline_dashboard(config_dir):
    storage_dir = os.path.join(config_dir, ".storage")
    assert dashboard_uses_streamline("streamline-dash", storage_dir) is True


def test_dashboard_uses_streamline_false_for_plain_dashboard(config_dir):
    storage_dir = os.path.join(config_dir, ".storage")
    assert dashboard_uses_streamline("map", storage_dir) is False


def test_dashboard_uses_streamline_false_for_default_dashboard(config_dir):
    storage_dir = os.path.join(config_dir, ".storage")
    assert dashboard_uses_streamline(None, storage_dir) is False


def test_dashboard_uses_streamline_false_for_missing_storage_file(config_dir):
    storage_dir = os.path.join(config_dir, ".storage")
    assert dashboard_uses_streamline("office-panel", storage_dir) is False


def test_dashboard_uses_streamline_false_for_unknown_url(config_dir):
    storage_dir = os.path.join(config_dir, ".storage")
    assert dashboard_uses_streamline("no-such-dashboard", storage_dir) is False


# ── extract_dashboard_config ──────────────────────────────────────────────────

def test_extract_dashboard_config_returns_inner_config():
    json_data = {
        "version": 1,
        "key": "lovelace.map",
        "data": {
            "config": {
                "views": [{"title": "Home"}]
            }
        },
    }
    result = extract_dashboard_config(json_data)
    assert result == {"views": [{"title": "Home"}]}


def test_extract_dashboard_config_excludes_envelope_keys():
    json_data = {"version": 1, "minor_version": 1, "key": "lovelace.map", "data": {"config": {"views": []}}}
    result = extract_dashboard_config(json_data)
    assert "version" not in result
    assert "key" not in result


# ── convert_to_yaml ───────────────────────────────────────────────────────────

def test_convert_to_yaml_produces_valid_yaml():
    data = {"views": [{"title": "Home", "cards": [{"type": "weather-forecast"}]}]}
    yaml_str = convert_to_yaml(data)
    parsed = ruamel.yaml.YAML().load(yaml_str)
    assert parsed["views"][0]["title"] == "Home"
    assert parsed["views"][0]["cards"][0]["type"] == "weather-forecast"


def test_convert_to_yaml_round_trips_booleans():
    data = {"auto_fit": True, "show_forecast": False}
    yaml_str = convert_to_yaml(data)
    parsed = ruamel.yaml.YAML().load(yaml_str)
    assert parsed["auto_fit"] is True
    assert parsed["show_forecast"] is False


def test_convert_to_yaml_preserves_key_insertion_order():
    data = {"z_last": 1, "a_first": 2, "m_middle": 3}
    yaml_str = convert_to_yaml(data)
    keys = [line.split(":")[0].strip() for line in yaml_str.strip().splitlines()]
    assert keys == ["z_last", "a_first", "m_middle"]


def test_convert_to_yaml_quotes_yaml11_boolean_keywords():
    """String values that are YAML 1.1 boolean keywords must be quoted.

    HA Core parses YAML 1.1 — unquoted `on`/`off`/`yes`/`no`/`true`/`false`
    become booleans. Strings carrying these literal values must round-trip
    as strings, not boolean coercions.
    """
    data = {
        "trigger_state": "on",
        "fallback_state": "off",
        "consent_yes": "yes",
        "consent_no": "no",
        "literal_true": "true",
        "literal_false": "false",
        "short_y": "y",
        "short_n": "n",
        "normal_string": "hello",
        "actual_bool": True,
    }
    yaml_str = convert_to_yaml(data)
    # Each YAML-1.1-keyword string value must appear quoted.
    for keyword in ("on", "off", "yes", "no", "true", "false", "y", "n"):
        assert f': "{keyword}"' in yaml_str, (
            f"Expected '{keyword}' to be quoted; got:\n{yaml_str}"
        )
    # Non-keyword strings stay plain.
    assert "normal_string: hello" in yaml_str
    # Actual booleans stay as booleans.
    assert "actual_bool: true" in yaml_str

    # Round-trip through a YAML 1.1 loader: every string value comes back as a string.
    yaml11 = ruamel.yaml.YAML()
    yaml11.version = (1, 1)
    parsed = yaml11.load(yaml_str)
    for k in (
        "trigger_state", "fallback_state", "consent_yes", "consent_no",
        "literal_true", "literal_false", "short_y", "short_n",
    ):
        assert isinstance(parsed[k], str), (
            f"{k}: expected str, got {type(parsed[k]).__name__} ({parsed[k]!r})"
        )
    assert parsed["actual_bool"] is True


def test_convert_to_yaml_keyword_quoting_case_insensitive():
    """YAML 1.1 boolean coercion is case-insensitive — On/OFF/Yes etc. also coerce."""
    data = {"a": "On", "b": "OFF", "c": "Yes", "d": "NO", "e": "True", "f": "FALSE"}
    yaml_str = convert_to_yaml(data)
    for value in ("On", "OFF", "Yes", "NO", "True", "FALSE"):
        assert f': "{value}"' in yaml_str, (
            f"Expected '{value}' to be quoted; got:\n{yaml_str}"
        )


def test_convert_to_yaml_output_is_block_style_not_flow():
    data = {"views": [{"cards": [{"type": "map"}]}]}
    yaml_str = convert_to_yaml(data)
    assert "{" not in yaml_str
    assert "}" not in yaml_str


# ── load_streamline_templates ─────────────────────────────────────────────────

def test_load_streamline_templates_returns_none_for_missing_file(tmp_path):
    result = load_streamline_templates(str(tmp_path / "nonexistent.yaml"))
    assert result is None


def test_load_streamline_templates_returns_none_for_invalid_yaml(tmp_path):
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text("key: [unclosed", encoding="utf-8")
    result = load_streamline_templates(str(bad_file))
    assert result is None


def test_load_streamline_templates_loads_valid_yaml(tmp_path):
    template_file = tmp_path / "streamline_templates.yaml"
    template_file.write_text(
        "my_template:\n  card:\n    type: button\n", encoding="utf-8"
    )
    result = load_streamline_templates(str(template_file))
    assert result is not None
    assert "my_template" in result


def test_load_streamline_templates_accepts_none(tmp_path):
    """None path returns None — for callers passing through optional config."""
    assert load_streamline_templates(None) is None


def test_load_streamline_templates_fallback_list_first_existing_wins(tmp_path):
    """When passed a list of candidate paths, use the first that exists."""
    primary = tmp_path / "missing.yaml"
    secondary = tmp_path / "secondary.yaml"
    secondary.write_text("from_secondary:\n  card:\n    type: button\n", encoding="utf-8")
    result = load_streamline_templates([str(primary), str(secondary)])
    assert result is not None
    assert "from_secondary" in result


def test_load_streamline_templates_fallback_list_none_when_all_missing(tmp_path):
    result = load_streamline_templates([
        str(tmp_path / "a.yaml"),
        str(tmp_path / "b.yaml"),
    ])
    assert result is None


def test_load_streamline_templates_fallback_primary_wins_when_present(tmp_path):
    primary = tmp_path / "primary.yaml"
    primary.write_text("from_primary:\n  card:\n    type: button\n", encoding="utf-8")
    secondary = tmp_path / "secondary.yaml"
    secondary.write_text("from_secondary:\n  card:\n    type: button\n", encoding="utf-8")
    result = load_streamline_templates([str(primary), str(secondary)])
    assert result is not None
    assert "from_primary" in result
    assert "from_secondary" not in result


def test_load_streamline_templates_supports_include_tag(tmp_path):
    """!include resolves relative to the parent file."""
    sub_dir = tmp_path / "templates"
    sub_dir.mkdir()
    (sub_dir / "light.yaml").write_text(
        "card:\n  type: light\n  entity: '[[entity]]'\n", encoding="utf-8"
    )
    (sub_dir / "weather.yaml").write_text(
        "card:\n  type: weather-forecast\n  entity: '[[entity]]'\n", encoding="utf-8"
    )
    main = tmp_path / "streamline_templates.yaml"
    main.write_text(
        "light_template: !include templates/light.yaml\n"
        "weather_template: !include templates/weather.yaml\n",
        encoding="utf-8",
    )
    result = load_streamline_templates(str(main))
    assert result is not None
    assert result["light_template"]["card"]["type"] == "light"
    assert result["weather_template"]["card"]["type"] == "weather-forecast"


def test_load_streamline_templates_supports_nested_include(tmp_path):
    """!include works recursively — an included file can itself !include."""
    deep = tmp_path / "deep" / "inner.yaml"
    deep.parent.mkdir(parents=True)
    deep.write_text(
        "card:\n  type: button\n  name: deeply nested\n", encoding="utf-8"
    )
    mid = tmp_path / "deep" / "outer.yaml"
    mid.write_text("button_template: !include inner.yaml\n", encoding="utf-8")
    main = tmp_path / "streamline_templates.yaml"
    main.write_text("buttons: !include deep/outer.yaml\n", encoding="utf-8")
    result = load_streamline_templates(str(main))
    assert result is not None
    assert result["buttons"]["button_template"]["card"]["name"] == "deeply nested"


# ── element: template body (parity with streamline-card picture-elements) ────

def test_expand_streamline_cards_supports_element_template_body():
    """Templates declaring `element:` instead of `card:` expand for picture-elements."""
    templates = {
        "icon_element_template": {
            "default": [{"icon_color": "white"}],
            "element": {
                "type": "icon",
                "icon": "[[icon]]",
                "style": {"color": "[[icon_color]]"},
            },
        },
    }
    config = {
        "type": "picture-elements",
        "image": "/local/floorplan.png",
        "elements": [
            {
                "type": "custom:streamline-card",
                "template": "icon_element_template",
                "variables": [{"icon": "mdi:lightbulb"}],
            }
        ],
    }
    expanded = expand_streamline_cards(config, templates)
    assert expanded["elements"][0]["type"] == "icon"
    assert expanded["elements"][0]["icon"] == "mdi:lightbulb"
    assert expanded["elements"][0]["style"]["color"] == "white"


def test_expand_streamline_cards_template_without_card_or_element_passes_through():
    """Malformed template (neither card nor element) is left untouched."""
    templates = {"broken_template": {"default": [{"x": 1}]}}
    config = {
        "type": "custom:streamline-card",
        "template": "broken_template",
    }
    expanded = expand_streamline_cards(config, templates)
    assert expanded["type"] == "custom:streamline-card"
    assert expanded["template"] == "broken_template"


# ── convert_dashboard ─────────────────────────────────────────────────────────

def test_convert_dashboard_named(config_dir, output_dir):
    result = convert_dashboard("map", config_dir, output_dir)
    assert result.success
    assert result.dashboard_id == "map"
    assert result.output_path is not None
    assert result.output_path.endswith("lovelace_map.yaml")
    assert os.path.exists(result.output_path)


def test_convert_dashboard_default(config_dir, output_dir):
    result = convert_dashboard(None, config_dir, output_dir)
    assert result.success
    assert result.dashboard_id == "lovelace"
    assert result.output_path is not None
    assert result.output_path.endswith("lovelace_lovelace.yaml")
    assert os.path.exists(result.output_path)


def test_convert_dashboard_output_contains_only_config(config_dir, output_dir):
    """YAML output must not contain the HA storage envelope fields."""
    result = convert_dashboard("map", config_dir, output_dir)
    assert result.success
    content = open(result.output_path, encoding="utf-8").read()
    assert "version:" not in content
    assert "minor_version:" not in content
    assert "key:" not in content


def test_convert_dashboard_output_is_valid_yaml(config_dir, output_dir):
    result = convert_dashboard("map", config_dir, output_dir)
    assert result.success
    content = open(result.output_path, encoding="utf-8").read()
    parsed = ruamel.yaml.YAML().load(content)
    assert "views" in parsed


def test_convert_dashboard_output_matches_input_config(config_dir, output_dir):
    """Parsed YAML output should match the original JSON config."""
    result = convert_dashboard("map", config_dir, output_dir)
    assert result.success

    # Load the original config from the fixture
    with open(os.path.join(config_dir, ".storage", "lovelace.map"), encoding="utf-8") as f:
        original_config = json.load(f)["data"]["config"]

    content = open(result.output_path, encoding="utf-8").read()
    parsed = ruamel.yaml.YAML().load(content)
    assert parsed["views"][0]["title"] == original_config["views"][0]["title"]
    assert parsed["views"][0]["type"] == original_config["views"][0]["type"]


def test_convert_dashboard_creates_output_dir(config_dir, tmp_path):
    new_output = str(tmp_path / "new" / "nested" / "dir")
    result = convert_dashboard("map", config_dir, new_output)
    assert result.success
    assert os.path.isdir(new_output)


def test_convert_dashboard_unknown_url_returns_failure(config_dir, output_dir):
    result = convert_dashboard("nonexistent-dashboard", config_dir, output_dir)
    assert not result.success
    assert result.error is not None
    assert result.output_path is None


def test_convert_dashboard_missing_storage_file_returns_failure(config_dir, output_dir):
    """office-panel is in the registry but has no fixture storage file."""
    result = convert_dashboard("office-panel", config_dir, output_dir)
    assert not result.success
    assert result.dashboard_id == "office_panel"
    assert result.error is not None


# ── ruamel.yaml library correctness ──────────────────────────────────────────

def test_ruamel_yaml_importable():
    import ruamel.yaml as ry
    assert ry is not None


def test_ruamel_yaml_oo_dump_produces_string():
    y = ruamel.yaml.YAML()
    y.default_flow_style = False
    buf = io.StringIO()
    y.dump({"key": "value", "items": [1, 2, 3]}, buf)
    output = buf.getvalue()
    assert "key: value" in output
    assert "- 1" in output
    assert "- 2" in output


def test_ruamel_yaml_oo_load_parses_correctly():
    y = ruamel.yaml.YAML()
    result = y.load("key: value\nlist:\n- 1\n- 2\n")
    assert result["key"] == "value"
    assert list(result["list"]) == [1, 2]


def test_ruamel_yaml_dump_load_round_trip():
    """Data written by convert_to_yaml must parse back to the original structure."""
    original = {
        "views": [
            {
                "title": "Home",
                "cards": [
                    {"type": "map", "auto_fit": True, "entities": ["person.example_user"]}
                ],
            }
        ]
    }
    yaml_str = convert_to_yaml(original)
    parsed = ruamel.yaml.YAML().load(yaml_str)
    assert parsed["views"][0]["title"] == "Home"
    assert parsed["views"][0]["cards"][0]["auto_fit"] is True
    assert "person.example_user" in parsed["views"][0]["cards"][0]["entities"]


# ── _normalize_variables ─────────────────────────────────────────────────────

def test_normalize_variables_dict_passthrough():
    assert _normalize_variables({"room": "bedroom"}) == {"room": "bedroom"}


def test_normalize_variables_array_merged():
    result = _normalize_variables([{"room": "bedroom"}, {"columns": 1}])
    assert result == {"room": "bedroom", "columns": 1}


def test_normalize_variables_empty():
    assert _normalize_variables(None) == {}
    assert _normalize_variables({}) == {}
    assert _normalize_variables([]) == {}


# ── _substitute_variables ────────────────────────────────────────────────────

def test_substitute_string_replacement():
    result = _substitute_variables("climate.[[room]]_thermostat", {"room": "bedroom"})
    assert result == "climate.bedroom_thermostat"


def test_substitute_whole_value_preserves_type():
    """A string that is only [[var]] should return the raw value type."""
    assert _substitute_variables("[[count]]", {"count": 42}) == 42
    assert _substitute_variables("[[flag]]", {"flag": True}) is True
    assert _substitute_variables("[[items]]", {"items": [1, 2]}) == [1, 2]


def test_substitute_partial_string_stays_string():
    result = _substitute_variables("entity.[[room]]_light", {"room": "kitchen"})
    assert result == "entity.kitchen_light"
    assert isinstance(result, str)


def test_substitute_nested_dicts():
    data = {"outer": {"inner": "[[val]]"}}
    result = _substitute_variables(data, {"val": "replaced"})
    assert result == {"outer": {"inner": "replaced"}}


def test_substitute_missing_variable_left_as_placeholder():
    result = _substitute_variables("[[undefined]]", {})
    assert result == "[[undefined]]"


def test_substitute_in_list_values():
    result = _substitute_variables(["[[a]]", "[[b]]"], {"a": "x", "b": "y"})
    assert result == ["x", "y"]


# ── expand_streamline_cards ──────────────────────────────────────────────────

def test_expand_simple_card():
    templates = {
        "btn": {"card": {"type": "button", "entity": "[[entity]]"}},
    }
    config = {"type": "custom:streamline-card", "template": "btn", "variables": {"entity": "light.kitchen"}}
    result = expand_streamline_cards(config, templates)
    assert result == {"type": "button", "entity": "light.kitchen"}


def test_expand_card_with_defaults():
    templates = {
        "thermo": {
            "default": [{"room": "habitat"}],
            "card": {"type": "climate", "entity": "climate.[[room]]_thermostat"},
        },
    }
    config = {"type": "custom:streamline-card", "template": "thermo", "variables": {}}
    result = expand_streamline_cards(config, templates)
    assert result["entity"] == "climate.habitat_thermostat"


def test_expand_card_variables_override_defaults():
    templates = {
        "thermo": {
            "default": [{"room": "habitat"}],
            "card": {"type": "climate", "entity": "climate.[[room]]_thermostat"},
        },
    }
    config = {"type": "custom:streamline-card", "template": "thermo", "variables": {"room": "bedroom"}}
    result = expand_streamline_cards(config, templates)
    assert result["entity"] == "climate.bedroom_thermostat"


def test_expand_preserves_javascript_keys():
    templates = {
        "btn": {
            "card": {
                "type": "button",
                "entity": "[[entity]]",
                "service_javascript": "return states['[[entity]]']?.attributes?.action;",
            },
        },
    }
    config = {"type": "custom:streamline-card", "template": "btn", "variables": {"entity": "sensor.cooking"}}
    result = expand_streamline_cards(config, templates)
    assert "service_javascript" in result
    assert "sensor.cooking" in result["service_javascript"]


def test_expand_nested_templates(streamline_templates_path):
    templates = load_streamline_templates(streamline_templates_path)
    config = {"type": "custom:streamline-card", "template": "nested_outer", "variables": {}}
    result = expand_streamline_cards(config, templates)
    assert result["type"] == "vertical-stack"
    cards = result["cards"]
    assert cards[0]["type"] == "custom:bubble-card"
    assert cards[0]["entity"] == "climate.bedroom_thermostat"
    assert cards[1]["type"] == "custom:bubble-card"
    assert cards[1]["entity"] == "light.kitchen"


def test_expand_missing_template_leaves_card_unchanged():
    templates = {}
    config = {"type": "custom:streamline-card", "template": "nonexistent", "variables": {}}
    result = expand_streamline_cards(config, templates)
    assert result == config


def test_expand_depth_limit_prevents_infinite_recursion(streamline_templates_path):
    """Circular template references should not cause infinite recursion."""
    templates = load_streamline_templates(streamline_templates_path)
    config = {"type": "custom:streamline-card", "template": "circular_a", "variables": {}}
    result = expand_streamline_cards(config, templates)
    assert result is not None


def test_expand_no_variables_key():
    templates = {"btn": {"card": {"type": "button", "name": "fixed"}}}
    config = {"type": "custom:streamline-card", "template": "btn"}
    result = expand_streamline_cards(config, templates)
    assert result == {"type": "button", "name": "fixed"}


def test_expand_array_variable_format():
    templates = {"btn": {"card": {"type": "button", "entity": "[[entity]]"}}}
    config = {
        "type": "custom:streamline-card",
        "template": "btn",
        "variables": [{"entity": "light.office"}],
    }
    result = expand_streamline_cards(config, templates)
    assert result == {"type": "button", "entity": "light.office"}


def test_expand_within_views_structure():
    """Expansion works when streamline cards are nested inside views/cards."""
    templates = {"btn": {"card": {"type": "button", "entity": "[[entity]]"}}}
    config = {
        "views": [
            {
                "cards": [
                    {"type": "custom:streamline-card", "template": "btn", "variables": {"entity": "light.a"}},
                    {"type": "weather-forecast"},
                ]
            }
        ]
    }
    result = expand_streamline_cards(config, templates)
    assert result["views"][0]["cards"][0] == {"type": "button", "entity": "light.a"}
    assert result["views"][0]["cards"][1] == {"type": "weather-forecast"}


# ── convert_dashboard with streamline expansion ─────────────────────────────

def test_convert_dashboard_with_streamline_expansion(config_dir, output_dir, streamline_templates_path):
    result = convert_dashboard("map", config_dir, output_dir, streamline_templates_path=streamline_templates_path)
    assert result.success


def test_convert_dashboard_without_templates_path_skips_expansion(config_dir, output_dir):
    result = convert_dashboard("map", config_dir, output_dir)
    assert result.success


def test_convert_dashboard_missing_templates_file_skips_gracefully(config_dir, output_dir):
    result = convert_dashboard("map", config_dir, output_dir, streamline_templates_path="/nonexistent/path.yaml")
    assert result.success


def test_convert_dashboard_is_idempotent(config_dir, output_dir):
    """Calling convert_dashboard twice produces identical output both times."""
    result1 = convert_dashboard("map", config_dir, output_dir)
    content1 = open(result1.output_path, encoding="utf-8").read()

    result2 = convert_dashboard("map", config_dir, output_dir)
    content2 = open(result2.output_path, encoding="utf-8").read()

    assert result1.success and result2.success
    assert result1.output_path == result2.output_path
    assert content1 == content2


def test_convert_dashboard_uses_dashboard_local_templates(tmp_path, output_dir):
    """`streamline_templates:` at dashboard config root is honoured (parity Method 2)."""
    # Build a minimal HA config dir with a registry + storage file containing
    # a dashboard-local streamline_templates block.
    storage = tmp_path / ".storage"
    storage.mkdir()
    (storage / "lovelace_dashboards").write_text(json.dumps({
        "data": {"items": [{"url_path": "local", "title": "Local", "icon": "mdi:home", "show_in_sidebar": True, "require_admin": False, "mode": "storage", "id": "local"}]},
        "key": "lovelace_dashboards", "version": 1,
    }))
    (storage / "lovelace.local").write_text(json.dumps({
        "data": {"config": {
            "streamline_templates": {
                "local_btn": {"card": {"type": "button", "name": "[[label]]"}},
            },
            "views": [{
                "title": "v",
                "cards": [
                    {"type": "custom:streamline-card", "template": "local_btn",
                     "variables": [{"label": "Hello"}]},
                ],
            }],
        }},
        "key": "lovelace.local", "version": 1,
    }))
    result = convert_dashboard("local", str(tmp_path), output_dir)
    assert result.success, result.error
    content = open(result.output_path, encoding="utf-8").read()
    parsed = ruamel.yaml.YAML().load(content)
    assert parsed["views"][0]["cards"][0]["type"] == "button"
    assert parsed["views"][0]["cards"][0]["name"] == "Hello"


def test_convert_dashboard_local_templates_override_global(tmp_path, output_dir):
    """Dashboard-local template wins on key conflict with global file."""
    storage = tmp_path / ".storage"
    storage.mkdir()
    (storage / "lovelace_dashboards").write_text(json.dumps({
        "data": {"items": [{"url_path": "local", "title": "Local", "icon": "mdi:home", "show_in_sidebar": True, "require_admin": False, "mode": "storage", "id": "local"}]},
        "key": "lovelace_dashboards", "version": 1,
    }))
    (storage / "lovelace.local").write_text(json.dumps({
        "data": {"config": {
            "streamline_templates": {
                "shared": {"card": {"type": "button", "name": "from-dashboard"}},
            },
            "views": [{
                "cards": [{"type": "custom:streamline-card", "template": "shared"}],
            }],
        }},
        "key": "lovelace.local", "version": 1,
    }))
    global_templates = tmp_path / "global.yaml"
    global_templates.write_text(
        "shared:\n  card:\n    type: button\n    name: from-global\n", encoding="utf-8"
    )
    result = convert_dashboard("local", str(tmp_path), output_dir, streamline_templates_path=str(global_templates))
    assert result.success
    content = open(result.output_path, encoding="utf-8").read()
    parsed = ruamel.yaml.YAML().load(content)
    assert parsed["views"][0]["cards"][0]["name"] == "from-dashboard"


def test_convert_dashboard_accepts_fallback_list(config_dir, output_dir, streamline_templates_path):
    """`streamline_templates_path` accepts a list of fallback paths."""
    result = convert_dashboard(
        "map", config_dir, output_dir,
        streamline_templates_path=["/nonexistent.yaml", streamline_templates_path],
    )
    assert result.success
