"""Solid Edge's application settings (Tools > Options) by name, not by number.

``Application.GetGlobalParameter`` / ``SetGlobalParameter`` take a member of
``ApplicationGlobalConstants``. The numbers are not hard-coded here: they are
read from the type library of the Solid Edge that is running, so a version
that renumbers, adds or drops a setting is followed automatically.

The library is found through the running application itself: its type info
names ``SolidEdgeFramework``, whose registered path gives the install's
``Program`` folder, and ``constant.tlb`` sits beside it. Verified on Solid
Edge 2026 (226): 497 settings, numbered 0-506 with ten gaps (199, 268, 269,
281, 420, 471-474, 488) -- removed members leave holes rather than shifting
the rest.

Some members still listed no longer answer (``seApplicationGlobalAutomaticSave``
and ``ColorBackground`` raise E_FAIL on 2026); a read reports that instead of
a value. Values come back as whatever Solid Edge holds -- a string
(``ApplicationColorScheme`` = "Office 2016 White"), a bool, an int or a
float -- and a write is coerced to the type of the current value.
"""

from __future__ import annotations

import functools
import os
from typing import Any

import pythoncom

ENUM_NAME = "ApplicationGlobalConstants"
PREFIX = "seApplicationGlobal"
CONSTANT_LIBRARY = "constant.tlb"


class SettingError(ValueError):
    """A setting name that does not resolve, or a value that does not fit it."""


def constant_library_path(app: Any) -> str:
    """Path of the running Solid Edge's constant.tlb."""
    typeinfo = app._oleobj_.GetTypeInfo()
    library, _ = typeinfo.GetContainingTypeLib()
    attr = library.GetLibAttr()
    framework = pythoncom.QueryPathOfRegTypeLib(attr[0], attr[3], attr[4], attr[1])
    path = os.path.join(os.path.dirname(framework.rstrip("\x00")), CONSTANT_LIBRARY)
    if not os.path.exists(path):
        raise SettingError(f"{CONSTANT_LIBRARY} not found beside {framework}")
    return path


@functools.lru_cache(maxsize=4)
def read_enum(path: str, enum_name: str = ENUM_NAME) -> dict[str, int]:
    """Every member of ``enum_name`` in the type library at ``path``, name -> value."""
    library = pythoncom.LoadTypeLib(path)
    for i in range(library.GetTypeInfoCount()):
        if library.GetDocumentation(i)[0] != enum_name:
            continue
        info = library.GetTypeInfo(i)
        members: dict[str, int] = {}
        for j in range(info.GetTypeAttr().cVars):
            desc = info.GetVarDesc(j)
            members[info.GetNames(desc.memid)[0]] = int(desc.value)
        return members
    raise SettingError(f"{enum_name} is not in {path}")


def short_name(full: str) -> str:
    return full[len(PREFIX) :] if full.startswith(PREFIX) else full


def resolve(name: str, members: dict[str, int]) -> tuple[str, int]:
    """'AutoSaveMinutes' or 'seApplicationGlobalAutoSaveMinutes' (any case) -> (full, id)."""
    wanted = name.strip().lower()
    if not wanted:
        raise SettingError("A setting name is required; list_settings shows them.")
    for full, value in members.items():
        if wanted in (full.lower(), short_name(full).lower()):
            return full, value
    close = [short_name(f) for f in members if wanted in f.lower()][:10]
    hint = f" Did you mean: {', '.join(close)}?" if close else " list_settings shows them."
    raise SettingError(f"No setting named {name!r}.{hint}")


def coerce(value: Any, current: Any) -> Any:
    """Convert ``value`` to the type of ``current`` (the setting's present value)."""
    if current is None:
        return value
    if isinstance(current, bool):
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "1", "yes", "on"):
            return True
        if text in ("false", "0", "no", "off"):
            return False
        raise SettingError(f"{value!r} is not a true/false value")
    if isinstance(current, int):
        if isinstance(value, float) and not value.is_integer():
            raise SettingError(f"{value!r} is not a whole number")
        try:
            return int(float(value))
        except (TypeError, ValueError) as exc:
            raise SettingError(f"{value!r} is not a whole number") from exc
    if isinstance(current, float):
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise SettingError(f"{value!r} is not a number") from exc
    return str(value)


def _plain(value: Any) -> Any:
    """A JSON-friendly copy of a COM value."""
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    return str(value)


def list_settings(
    app: Any, contains: str = "", with_values: bool = True, limit: int = 100
) -> dict[str, Any]:
    members = read_enum(constant_library_path(app))
    needle = contains.strip().lower()
    matches = sorted((v, f) for f, v in members.items() if not needle or needle in f.lower())
    shown = matches[: max(1, limit)]
    items: list[dict[str, Any]] = []
    for value, full in shown:
        item: dict[str, Any] = {"name": short_name(full), "id": value}
        if with_values:
            try:
                item["value"] = _plain(app.GetGlobalParameter(value))
            except Exception:
                item["readable"] = False
        items.append(item)
    return {
        "status": "listed",
        "total": len(matches),
        "shown": len(items),
        "truncated": len(matches) > len(items),
        "settings": items,
    }


def get_setting(app: Any, name: str) -> dict[str, Any]:
    full, setting_id = resolve(name, read_enum(constant_library_path(app)))
    try:
        value = app.GetGlobalParameter(setting_id)
    except Exception:
        return {
            "error": f"{short_name(full)} (id {setting_id}) cannot be read on this "
            "Solid Edge: it is listed in the type library but no longer answers "
            "(about a fifth of the list on 2026 does this).",
            "unsupported": True,
            "name": short_name(full),
            "id": setting_id,
        }
    return {"status": "success", "name": short_name(full), "id": setting_id, "value": _plain(value)}


def set_setting(app: Any, name: str, value: Any) -> dict[str, Any]:
    """Write a setting and report what it held before and holds after.

    Settings persist across Solid Edge sessions; ``old_value`` is what to
    write back to undo the change.
    """
    full, setting_id = resolve(name, read_enum(constant_library_path(app)))
    try:
        old = app.GetGlobalParameter(setting_id)
    except Exception:
        old = None
    new = coerce(value, old)
    app.SetGlobalParameter(setting_id, new)
    try:
        after = app.GetGlobalParameter(setting_id)
    except Exception:
        after = None
    result: dict[str, Any] = {
        "status": "set",
        "name": short_name(full),
        "id": setting_id,
        "old_value": _plain(old),
        "value": _plain(after),
        "note": "Settings persist across sessions; set old_value back to undo.",
    }
    if after is not None and after != new:
        result["warning"] = f"Solid Edge holds {after!r} after writing {new!r}."
    return result
