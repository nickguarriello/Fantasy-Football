"""Every module must import cleanly with no ESPN credentials on disk (DESIGN.md §7.7)."""
import importlib

import pytest

MODULES = [
    "config",
    "main",
    "pipeline.init_db",
    "pipeline.fetch_espn",
    "pipeline.fetch_projections",
    "pipeline.fetch_nfl",
    "pipeline.crosswalk",
    "pipeline.transform",
    "pipeline.validate",
    "pipeline.evaluate",
    "pipeline.draft",
    "pipeline.report",
    "pipeline.health",
]


@pytest.mark.parametrize("module_name", MODULES)
def test_imports_without_credentials(module_name):
    importlib.import_module(module_name)


def test_credentials_fall_back_to_none_when_import_fails(monkeypatch):
    """config.py's try/except must degrade to None, not crash, when espn_credentials is
    unimportable — true in CI (the file is never committed) and in local dev before it's
    written. Forced here via sys.modules so the test doesn't depend on the real file's
    presence on the machine running it."""
    import sys

    import config

    monkeypatch.setitem(sys.modules, "espn_credentials", None)
    importlib.reload(config)
    try:
        assert config.ESPN_SWID is None
        assert config.ESPN_S2 is None
    finally:
        importlib.reload(config)  # restore real state for any tests/imports after this one
