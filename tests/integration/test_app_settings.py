"""Application settings by name, against the running Solid Edge's own type library."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_names_come_from_the_installed_library(solid_edge):
    from solidedge_mcp.backends import app_settings

    app = solid_edge.get_application()
    members = app_settings.read_enum(app_settings.constant_library_path(app))
    assert len(members) > 400
    assert members["seApplicationGlobalAutoSaveMinutes"] == 247  # Solid Edge 2026


def test_list_and_get(solid_edge):
    r = solid_edge.list_settings("autosave")
    names = {s["name"] for s in r["settings"]}
    assert "AutoSaveMinutes" in names
    g = solid_edge.get_setting("ApplicationColorScheme")
    assert isinstance(g["value"], str)


def test_set_and_put_back(solid_edge):
    before = solid_edge.get_setting("PartandAsmUndoSteps")["value"]
    try:
        r = solid_edge.set_setting("PartandAsmUndoSteps", before + 1)
        assert (r["old_value"], r["value"]) == (before, before + 1)
    finally:
        back = solid_edge.set_setting("PartandAsmUndoSteps", before)
    assert back["value"] == before
