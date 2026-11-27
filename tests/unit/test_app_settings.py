"""Unit tests for app settings by name (backends/app_settings.py)."""

from unittest.mock import MagicMock

import pytest

from solidedge_mcp.backends import app_settings
from solidedge_mcp.backends.app_settings import SettingError, coerce, resolve

MEMBERS = {
    "seApplicationGlobalAutoSaveMinutes": 247,
    "seApplicationGlobalAutoPreserveDocAutoSave": 246,
    "seApplicationGlobalApplicationColorScheme": 312,
    "seApplicationGlobalShowOrientationTriad": 194,
    "seApplicationGlobalAutomaticSave": 12,
}


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(app_settings, "constant_library_path", lambda a: "constant.tlb")
    monkeypatch.setattr(app_settings, "read_enum", lambda path: MEMBERS)
    values = {247: 60, 246: False, 312: "Office 2016 White", 194: True}
    fake = MagicMock()

    def get(pid):
        if pid not in values:
            raise RuntimeError("E_FAIL")
        return values[pid]

    def set_(pid, value):
        values[pid] = value

    fake.GetGlobalParameter.side_effect = get
    fake.SetGlobalParameter.side_effect = set_
    fake.values = values
    return fake


class TestResolve:
    @pytest.mark.parametrize(
        "name", ["AutoSaveMinutes", "autosaveminutes", "seApplicationGlobalAutoSaveMinutes"]
    )
    def test_short_full_and_case(self, name):
        assert resolve(name, MEMBERS) == ("seApplicationGlobalAutoSaveMinutes", 247)

    def test_suggests_close_names(self):
        with pytest.raises(SettingError, match="AutoSaveMinutes"):
            resolve("AutoSaveMinute", MEMBERS)

    def test_empty(self):
        with pytest.raises(SettingError):
            resolve(" ", MEMBERS)


class TestCoerce:
    @pytest.mark.parametrize(
        ("value", "current", "expected"),
        [
            ("true", False, True),
            ("off", True, False),
            (True, False, True),
            ("101", 100, 101),
            (12.0, 100, 12),
            ("0.5", 1.0, 0.5),
            (3, "x", "3"),
            ("anything", None, "anything"),
        ],
    )
    def test_to_current_type(self, value, current, expected):
        result = coerce(value, current)
        assert result == expected and type(result) is type(expected)

    @pytest.mark.parametrize(("value", "current"), [("maybe", True), (1.5, 100), ("x", 1.0)])
    def test_refuses(self, value, current):
        with pytest.raises(SettingError):
            coerce(value, current)


class TestListGetSet:
    def test_list_filters_and_reads(self, app):
        r = app_settings.list_settings(app, "autosave")
        assert r["total"] == 2
        assert {s["name"]: s["value"] for s in r["settings"]} == {
            "AutoPreserveDocAutoSave": False,
            "AutoSaveMinutes": 60,
        }

    def test_list_marks_unreadable(self, app):
        r = app_settings.list_settings(app, "automatic")
        assert r["settings"] == [{"name": "AutomaticSave", "id": 12, "readable": False}]

    def test_list_limit(self, app):
        r = app_settings.list_settings(app, "", limit=2)
        assert r["shown"] == 2 and r["truncated"] is True and r["total"] == len(MEMBERS)

    def test_get(self, app):
        r = app_settings.get_setting(app, "ApplicationColorScheme")
        assert r == {
            "status": "success",
            "name": "ApplicationColorScheme",
            "id": 312,
            "value": "Office 2016 White",
        }
        app.GetGlobalParameter.assert_called_with(312)

    def test_get_unreadable(self, app):
        r = app_settings.get_setting(app, "AutomaticSave")
        assert r["unsupported"] is True and "no longer answers" in r["error"]

    def test_set_reports_old_and_new(self, app):
        r = app_settings.set_setting(app, "AutoSaveMinutes", "30")
        app.SetGlobalParameter.assert_called_once_with(247, 30)
        assert (r["old_value"], r["value"]) == (60, 30)

    def test_set_refuses_before_writing(self, app):
        with pytest.raises(SettingError):
            app_settings.set_setting(app, "ShowOrientationTriad", "maybe")
        app.SetGlobalParameter.assert_not_called()

    def test_set_warns_when_value_does_not_stick(self, app):
        app.SetGlobalParameter.side_effect = lambda pid, v: None
        r = app_settings.set_setting(app, "AutoSaveMinutes", 30)
        assert "warning" in r


class TestConnectionWrappers:
    def test_setting_error_becomes_error_dict(self, monkeypatch):
        from solidedge_mcp.backends.connection import SolidEdgeConnection

        conn = SolidEdgeConnection()
        monkeypatch.setattr(conn, "_get_app", lambda: MagicMock())

        def boom(*a, **k):
            raise SettingError("No setting named 'x'.")

        monkeypatch.setattr(app_settings, "get_setting", boom)
        assert conn.get_setting("x") == {"error": "No setting named 'x'."}
