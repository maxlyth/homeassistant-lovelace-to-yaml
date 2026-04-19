"""Integration tests for pyscript/apps/lovelace_to_yaml/__init__.py.

These tests exercise the pyscript glue layer under a mocked pyscript
environment.  They are designed to catch runtime bugs that pure unit tests of
lovelace_core.py cannot detect, such as:

  - Pyscript's module system async-wrapping imported functions, causing
    ``'coroutine' object has no attribute 'success'`` errors in executors.
  - ``open()`` or ``log`` being unavailable in the wrong execution context.
  - Hardcoded deployment paths breaking test execution.

All tests use the ``pyscript_app`` fixture (conftest.py) which injects mocks
and imports ``__init__.py`` fresh for each test.
"""

import inspect
import os


# ── A. Module loading ─────────────────────────────────────────────────────────


def test_module_loads_successfully(pyscript_app):
    """__init__.py must import without error under the mock environment.

    This single test would have caught all three historical deployment bugs.
    """
    mod, _ = pyscript_app
    assert mod is not None


def test_module_reads_config_from_app_config(pyscript_app, config_dir, output_dir, streamline_templates_path):
    """Module-level config constants must reflect values from pyscript.app_config."""
    mod, _ = pyscript_app
    assert mod.CONFIG_DIR == config_dir
    assert mod.OUTPUT_DIR == output_dir
    assert mod.STREAMLINE_TEMPLATES_PATH == streamline_templates_path


def test_lovelace_core_loaded_as_plain_module(pyscript_app):
    """lovelace_core must be loaded as a plain Python module (not pyscript-wrapped).

    If pyscript's module system were used, convert_dashboard would be an async
    coroutine function.  It must be a regular callable.
    """
    mod, _ = pyscript_app
    assert hasattr(mod.lovelace_core, "convert_dashboard")
    assert not inspect.iscoroutinefunction(mod.lovelace_core.convert_dashboard)


def test_lovelace_core_module_name(pyscript_app):
    """lovelace_core must be loaded as a standalone module, not a submodule."""
    mod, _ = pyscript_app
    assert mod.lovelace_core.__name__ == "lovelace_core"


# ── B. _do_convert (executor function) ───────────────────────────────────────


def test_do_convert_is_not_coroutine(pyscript_app):
    """_do_convert must remain a regular callable after @pyscript_executor.

    In the real runtime @pyscript_executor returns a coroutine; the mock must
    keep it synchronous so tests can call it directly.
    """
    mod, _ = pyscript_app
    assert callable(mod._do_convert)
    assert not inspect.iscoroutinefunction(mod._do_convert)


def test_do_convert_successful(pyscript_app, output_dir):
    """_do_convert("map") must create the YAML output file."""
    mod, _ = pyscript_app
    mod._do_convert("map")
    assert os.path.exists(os.path.join(output_dir, "lovelace_map.yaml"))


def test_do_convert_default_dashboard(pyscript_app, output_dir):
    """_do_convert(None) must convert the default dashboard."""
    mod, _ = pyscript_app
    mod._do_convert(None)
    assert os.path.exists(os.path.join(output_dir, "lovelace_lovelace.yaml"))


def test_do_convert_failure_logs_error(pyscript_app, caplog):
    """_do_convert with an unknown dashboard must log an error via _LOGGER."""
    import logging
    mod, _ = pyscript_app
    with caplog.at_level(logging.ERROR, logger="custom_components.pyscript.apps.lovelace_to_yaml"):
        mod._do_convert("nonexistent-dashboard")
    assert any("conversion failed" in r.message for r in caplog.records)


def test_do_convert_uses_stdlib_logging_not_pyscript_log(pyscript_app):
    """_do_convert must use _LOGGER (stdlib), not log (pyscript global).

    log is only available in pyscript's async context, not in executor threads.
    """
    src = inspect.getsource(pyscript_app[0]._do_convert)
    assert "_LOGGER" in src
    # "log." should not appear inside _do_convert
    assert "log.info" not in src
    assert "log.error" not in src


# ── C. lovelace_updated_event (event trigger) ─────────────────────────────────


def test_event_trigger_decorator_recorded(pyscript_app):
    """@event_trigger must have recorded the event name on the handler."""
    mod, _ = pyscript_app
    assert hasattr(mod.lovelace_updated_event, "_event_trigger")
    assert mod.lovelace_updated_event._event_trigger == "lovelace_updated"


def test_event_handler_calls_do_convert(pyscript_app, output_dir):
    """lovelace_updated_event(url_path='map') must produce YAML output."""
    mod, _ = pyscript_app
    mod.lovelace_updated_event(url_path="map")
    assert os.path.exists(os.path.join(output_dir, "lovelace_map.yaml"))


def test_event_handler_logs_via_pyscript_log(pyscript_app):
    """lovelace_updated_event must call log.info (pyscript global), not _LOGGER."""
    mod, log_proxy = pyscript_app
    mod.lovelace_updated_event(url_path="map")
    assert any("lovelace_updated" in msg for msg in log_proxy.messages("info"))


def test_event_handler_debounces_via_task_unique(pyscript_app, task_proxy):
    """lovelace_updated_event must call task.unique per-url_path for coalescing.

    This is the core of the stale-read fix (issue #3): rapid successive saves
    for the same dashboard must collapse into a single conversion that runs
    after HA's Store debounce has flushed the final state to disk.
    """
    mod, _ = pyscript_app
    mod.lovelace_updated_event(url_path="map")
    assert task_proxy.unique_calls == ["lovelace_to_yaml_convert_map"]


def test_event_handler_sleeps_before_converting(pyscript_app, task_proxy):
    """lovelace_updated_event must task.sleep before calling _do_convert.

    The sleep must exceed HA's LovelaceStorage disk-write debounce so the
    executor reads the final JSON, not a stale pre-write state.
    """
    mod, _ = pyscript_app
    mod.lovelace_updated_event(url_path="map")
    assert len(task_proxy.sleep_calls) == 1
    assert task_proxy.sleep_calls[0] == mod.DEBOUNCE_SECONDS
    # The debounce must be long enough to clear HA's default Store debounce.
    assert mod.DEBOUNCE_SECONDS >= 5


def test_event_handler_uses_distinct_unique_name_per_url(pyscript_app, task_proxy):
    """Different url_paths must get distinct task.unique names so they don't
    cancel each other's debounce timers."""
    mod, _ = pyscript_app
    mod.lovelace_updated_event(url_path="map")
    mod.lovelace_updated_event(url_path=None)
    assert task_proxy.unique_calls == [
        "lovelace_to_yaml_convert_map",
        "lovelace_to_yaml_convert_None",
    ]


def test_event_handler_accepts_unknown_kwargs(pyscript_app):
    """lovelace_updated_event must tolerate extra event-data kwargs from HA.

    HA's REST API and future HA versions may attach additional event data
    fields to ``lovelace_updated``.  The handler must accept and ignore them,
    otherwise it raises TypeError and the conversion never runs.
    """
    mod, _ = pyscript_app
    # Must not raise
    mod.lovelace_updated_event(url_path="map", unexpected_extra="value")


def test_debounce_seconds_configurable_via_app_config(monkeypatch, config_dir, output_dir, streamline_templates_path):
    """debounce_seconds in app_config must override the default."""
    import builtins
    import importlib.util
    import sys

    from pyscript_mock import (
        LogProxy,
        PyscriptNamespace,
        TaskProxy,
        event_trigger,
        pyscript_executor,
        service,
    )

    ns = PyscriptNamespace(
        app_config={
            "config_dir": config_dir,
            "output_dir": output_dir,
            "streamline_templates_path": streamline_templates_path,
            "core_module_path": os.path.abspath(os.path.join(
                os.path.dirname(__file__), "..", "pyscript", "apps",
                "lovelace_to_yaml", "lovelace_core.py",
            )),
            "debounce_seconds": 3.5,
        }
    )
    monkeypatch.setattr(builtins, "pyscript", ns, raising=False)
    monkeypatch.setattr(builtins, "pyscript_executor", pyscript_executor, raising=False)
    monkeypatch.setattr(builtins, "event_trigger", event_trigger, raising=False)
    monkeypatch.setattr(builtins, "service", service, raising=False)
    monkeypatch.setattr(builtins, "log", LogProxy(), raising=False)
    monkeypatch.setattr(builtins, "task", TaskProxy(), raising=False)

    sys.modules.pop("lovelace_to_yaml_integration_cfg", None)
    init_py = os.path.join(
        os.path.dirname(__file__), "..", "pyscript", "apps",
        "lovelace_to_yaml", "__init__.py",
    )
    spec = importlib.util.spec_from_file_location(
        "lovelace_to_yaml_integration_cfg", os.path.abspath(init_py)
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["lovelace_to_yaml_integration_cfg"] = mod
    spec.loader.exec_module(mod)

    try:
        assert mod.DEBOUNCE_SECONDS == 3.5
    finally:
        sys.modules.pop("lovelace_to_yaml_integration_cfg", None)


# ── D. lovelace_convert (service) ────────────────────────────────────────────


def test_service_decorator_recorded(pyscript_app):
    """@service must have marked the service function."""
    mod, _ = pyscript_app
    assert getattr(mod.lovelace_convert, "_is_service", False) is True


def test_service_creates_output(pyscript_app, output_dir):
    """lovelace_convert(url='map') must produce YAML output."""
    mod, _ = pyscript_app
    mod.lovelace_convert(url="map")
    assert os.path.exists(os.path.join(output_dir, "lovelace_map.yaml"))


def test_service_with_none_converts_default(pyscript_app, output_dir):
    """lovelace_convert(url=None) must convert the default dashboard."""
    mod, _ = pyscript_app
    mod.lovelace_convert(url=None)
    assert os.path.exists(os.path.join(output_dir, "lovelace_lovelace.yaml"))


# ── E. streamline_templates_changed (folder_watcher handler) ─────────────────


def test_folder_watcher_event_trigger_registered(pyscript_app):
    """@event_trigger must record 'folder_watcher' on the handler."""
    mod, _ = pyscript_app
    assert hasattr(mod.streamline_templates_changed, "_event_trigger")
    assert mod.streamline_templates_changed._event_trigger == "folder_watcher"


def test_folder_watcher_converts_streamline_dashboards(pyscript_app, output_dir):
    """Matching event must reconvert dashboards that use custom:streamline-card."""
    mod, _ = pyscript_app
    mod.streamline_templates_changed(
        path="/config/www/community/streamline-card/streamline_templates.yaml",
        event_type="modified",
    )
    assert os.path.exists(os.path.join(output_dir, "lovelace_streamline_dash.yaml"))


def test_folder_watcher_does_not_convert_plain_dashboards(pyscript_app, output_dir):
    """Reconvert must skip dashboards with no custom:streamline-card reference."""
    mod, _ = pyscript_app
    mod.streamline_templates_changed(
        path="/config/www/community/streamline-card/streamline_templates.yaml",
        event_type="modified",
    )
    assert not os.path.exists(os.path.join(output_dir, "lovelace_map.yaml"))
    assert not os.path.exists(os.path.join(output_dir, "lovelace_lovelace.yaml"))


def test_folder_watcher_ignores_unrelated_files(pyscript_app, output_dir):
    """Events for other files must not trigger reconversion."""
    mod, _ = pyscript_app
    mod.streamline_templates_changed(path="/config/some_other_file.yaml", event_type="modified")
    assert not any(os.listdir(output_dir))


def test_folder_watcher_ignores_deleted_event(pyscript_app, output_dir):
    """'deleted' event_type must not trigger reconversion."""
    mod, _ = pyscript_app
    mod.streamline_templates_changed(
        path="/config/www/community/streamline-card/streamline_templates.yaml",
        event_type="deleted",
    )
    assert not any(os.listdir(output_dir))


def test_folder_watcher_handles_closed_event(pyscript_app, output_dir):
    """'closed' event_type (vim-style save) must trigger reconversion."""
    mod, _ = pyscript_app
    mod.streamline_templates_changed(
        path="/config/www/community/streamline-card/streamline_templates.yaml",
        event_type="closed",
    )
    assert os.path.exists(os.path.join(output_dir, "lovelace_streamline_dash.yaml"))


def test_folder_watcher_logs_via_pyscript_log(pyscript_app):
    """streamline_templates_changed must call log.info (pyscript global)."""
    mod, log_proxy = pyscript_app
    mod.streamline_templates_changed(
        path="/config/www/community/streamline-card/streamline_templates.yaml",
        event_type="modified",
    )
    assert any("streamline_templates.yaml" in msg for msg in log_proxy.messages("info"))


def test_reconvert_uses_stdlib_logging_not_pyscript_log(pyscript_app):
    """_reconvert_streamline_dashboards must use _LOGGER, not log."""
    src = inspect.getsource(pyscript_app[0]._reconvert_streamline_dashboards)
    assert "_LOGGER" in src
    assert "log.info" not in src
    assert "log.error" not in src
