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


def test_credentials_default_to_none_without_file():
    import config

    assert config.ESPN_SWID is None
    assert config.ESPN_S2 is None
