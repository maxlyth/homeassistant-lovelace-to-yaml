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
    expand_streamline_cards,
    extract_dashboard_config,
    get_lovelace_id_from_url,
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
