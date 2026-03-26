"""lovelace_to_yaml — Auto-convert Lovelace dashboards from JSON to YAML.

See https://github.com/maxlyth/homeassistant-lovelace-to-yaml for documentation.
"""

import importlib.util as _ilu
import logging as _logging
import os

_cfg = pyscript.app_config or {}
CONFIG_DIR = _cfg.get("config_dir", "/config")
OUTPUT_DIR = _cfg.get("output_dir", "/config/lovelace_yaml")
STREAMLINE_TEMPLATES_PATH = _cfg.get(
    "streamline_templates_path",
    "/config/www/community/streamline-card/streamline_templates.yaml",
)

# Load lovelace_core as a plain Python module via importlib so that its
# functions remain regular Python callables (not pyscript-wrapped coroutines).
# This is required because pyscript's module system async-wraps imported
# functions, which prevents them from being called from executor threads.
_core_path = _cfg.get(
    "core_module_path",
    "/config/pyscript/apps/lovelace_to_yaml/lovelace_core.py",
)
_spec = _ilu.spec_from_file_location("lovelace_core", _core_path)
lovelace_core = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(lovelace_core)

_LOGGER = _logging.getLogger("custom_components.pyscript.apps.lovelace_to_yaml")

EVENT_LOVELACE_UPDATED = "lovelace_updated"
EVENT_FOLDER_WATCHER = "folder_watcher"


# ── Core conversion ───────────────────────────────────────────────────────────

@pyscript_executor
def _do_convert(url):
    result = lovelace_core.convert_dashboard(
        url,
        CONFIG_DIR,
        OUTPUT_DIR,
        streamline_templates_path=STREAMLINE_TEMPLATES_PATH,
    )
    if result.success:
        _LOGGER.info("lovelace_to_yaml: converted '%s' → %s", result.dashboard_id, result.output_path)
    else:
        _LOGGER.error("lovelace_to_yaml: conversion failed: %s", result.error)


@pyscript_executor
def _reconvert_streamline_dashboards():
    storage_dir = os.path.join(CONFIG_DIR, ".storage")
    urls = lovelace_core.list_dashboard_urls(storage_dir)
    converted = 0
    for url in urls:
        if not lovelace_core.dashboard_uses_streamline(url, storage_dir):
            continue
        result = lovelace_core.convert_dashboard(url, CONFIG_DIR, OUTPUT_DIR, streamline_templates_path=STREAMLINE_TEMPLATES_PATH)
        if result.success:
            _LOGGER.info("lovelace_to_yaml: reconverted '%s' → %s", result.dashboard_id, result.output_path)
            converted += 1
        else:
            _LOGGER.error("lovelace_to_yaml: reconversion failed for '%s': %s", url, result.error)
    _LOGGER.info("lovelace_to_yaml: streamline reconvert complete (%d dashboards)", converted)


# ── Triggers ──────────────────────────────────────────────────────────────────

@event_trigger(EVENT_LOVELACE_UPDATED)
def lovelace_updated_event(url_path=None):
    log.info(f"lovelace_to_yaml: lovelace_updated event (url_path={url_path!r})")
    _do_convert(url_path)


@event_trigger(EVENT_FOLDER_WATCHER)
def streamline_templates_changed(**kwargs):
    path = kwargs.get("path", "")
    event_type = kwargs.get("event_type", "")
    if not path.endswith("streamline_templates.yaml"):
        return
    if event_type not in ("modified", "created", "closed"):
        return
    log.info(f"lovelace_to_yaml: streamline_templates.yaml changed ({event_type}), reconverting affected dashboards")
    _reconvert_streamline_dashboards()


@service
def lovelace_convert(url=None):
    """yaml
name: Lovelace Convert
description: Manually convert a Lovelace dashboard from JSON to YAML.
fields:
  url:
    description: >
      URL path of the dashboard to convert (e.g. 'office-panel').
      Leave empty to convert the default dashboard.
    example: office-panel
    required: false
    selector:
      text:
"""
    _do_convert(url)
