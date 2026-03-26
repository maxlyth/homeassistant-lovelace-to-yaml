import builtins
import importlib.util
import json
import os
import sys

import pytest

# Allow tests to import lovelace_core directly (as pyscript would at runtime)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pyscript", "apps", "lovelace_to_yaml"))
# Allow the pyscript_app fixture to import pyscript_mock from the same directory
sys.path.insert(0, os.path.dirname(__file__))

_APP_DIR = os.path.join(os.path.dirname(__file__), "..", "pyscript", "apps", "lovelace_to_yaml")
_INIT_PY = os.path.join(_APP_DIR, "__init__.py")
_CORE_PY = os.path.join(_APP_DIR, "lovelace_core.py")
_INTEGRATION_MOD_NAME = "lovelace_to_yaml_integration"

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def config_dir(tmp_path):
    """Temporary HA config directory pre-populated with fixture storage files."""
    storage = tmp_path / ".storage"
    storage.mkdir()
    for name in ["lovelace_dashboards", "lovelace.map", "lovelace.lovelace", "lovelace.streamline_dash"]:
        src = os.path.join(FIXTURES_DIR, f"{name}.json")
        (storage / name).write_text(
            open(src, encoding="utf-8").read(), encoding="utf-8"
        )
    return str(tmp_path)


@pytest.fixture
def output_dir(tmp_path):
    """Temporary output directory for YAML files."""
    out = tmp_path / "lovelace_yaml"
    out.mkdir()
    return str(out)


@pytest.fixture
def streamline_templates_path():
    """Path to the streamline templates test fixture."""
    return os.path.join(FIXTURES_DIR, "streamline_templates.yaml")


@pytest.fixture
def pyscript_app(config_dir, output_dir, streamline_templates_path, monkeypatch):
    """Load __init__.py under mocked pyscript globals.

    Injects minimal mock implementations of the five pyscript built-ins used
    by the app (``pyscript``, ``pyscript_executor``, ``event_trigger``,
    ``service``, ``log``) then imports ``__init__.py`` via importlib so the
    full module-level code path runs under the mocks.

    Yields ``(module, log_proxy)`` where ``log_proxy`` is the :class:`LogProxy`
    instance bound as ``log`` so tests can assert on log output.
    """
    from pyscript_mock import (
        LogProxy,
        PyscriptNamespace,
        event_trigger,
        pyscript_executor,
        service,
    )

    log_proxy = LogProxy()
    ns = PyscriptNamespace(
        app_config={
            "config_dir": config_dir,
            "output_dir": output_dir,
            "streamline_templates_path": streamline_templates_path,
            "core_module_path": os.path.abspath(_CORE_PY),
        }
    )

    monkeypatch.setattr(builtins, "pyscript", ns, raising=False)
    monkeypatch.setattr(builtins, "pyscript_executor", pyscript_executor, raising=False)
    monkeypatch.setattr(builtins, "event_trigger", event_trigger, raising=False)
    monkeypatch.setattr(builtins, "service", service, raising=False)
    monkeypatch.setattr(builtins, "log", log_proxy, raising=False)

    # Remove any cached module so each fixture call gets a fresh import.
    sys.modules.pop(_INTEGRATION_MOD_NAME, None)

    spec = importlib.util.spec_from_file_location(_INTEGRATION_MOD_NAME, os.path.abspath(_INIT_PY))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_INTEGRATION_MOD_NAME] = mod
    spec.loader.exec_module(mod)

    yield mod, log_proxy

    sys.modules.pop(_INTEGRATION_MOD_NAME, None)
