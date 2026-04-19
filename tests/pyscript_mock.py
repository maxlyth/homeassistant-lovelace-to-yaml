"""Minimal mocks for pyscript built-in globals used in __init__.py.

These are injected into builtins before importing the pyscript app module so
that the integration tests can exercise the full __init__.py code path without
a running Home Assistant or pyscript instance.
"""


class PyscriptNamespace:
    """Mock for the ``pyscript`` built-in object.

    In the real runtime, ``pyscript.app_config`` is populated from the
    ``apps:`` block in ``configuration.yaml``.
    """

    def __init__(self, app_config: dict):
        self.app_config = app_config


def pyscript_executor(fn):
    """Identity decorator — keeps the function synchronously callable.

    In the real runtime this schedules the function on a thread-pool executor
    and returns a coroutine.  In tests we want it to run synchronously so we
    can call it directly and inspect the result.
    """
    return fn


def event_trigger(event_name):
    """Decorator factory that records the trigger event name on the function.

    In the real runtime this registers the function as an event listener.
    """

    def decorator(fn):
        fn._event_trigger = event_name
        return fn

    return decorator


def service(fn):
    """Identity decorator that marks the function as a registered service.

    In the real runtime this registers the function as an HA service.
    """
    fn._is_service = True
    return fn


class TaskProxy:
    """Mock for the ``task`` built-in used in pyscript async contexts.

    In the real runtime, ``task.unique(name)`` cancels any running task with
    the same name and claims the name for the caller, and ``task.sleep(s)``
    suspends the caller for s seconds.  In tests we don't actually sleep —
    we just record calls so tests can assert on the wiring.
    """

    def __init__(self):
        self.unique_calls = []
        self.sleep_calls = []

    def unique(self, name, kill_me=False):
        self.unique_calls.append(name)

    def sleep(self, seconds):
        self.sleep_calls.append(seconds)


class LogProxy:
    """Mock for the ``log`` built-in used in pyscript async contexts.

    Records all calls so tests can assert on log output.
    """

    def __init__(self):
        self.calls = []

    def _record(self, level, msg, *args):
        self.calls.append((level, msg % args if args else msg))

    def debug(self, msg, *args):
        self._record("debug", msg, *args)

    def info(self, msg, *args):
        self._record("info", msg, *args)

    def warning(self, msg, *args):
        self._record("warning", msg, *args)

    def error(self, msg, *args):
        self._record("error", msg, *args)

    def messages(self, level=None):
        """Return recorded messages, optionally filtered by level."""
        if level is None:
            return [msg for _, msg in self.calls]
        return [msg for lvl, msg in self.calls if lvl == level]
