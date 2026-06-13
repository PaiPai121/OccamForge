from pathlib import Path

from assetforge.blender.locator import BlenderLocator
from assetforge.core.config import UserConfigStore


def test_locator_uses_saved_configuration_first(tmp_path: Path, monkeypatch) -> None:
    store = UserConfigStore(tmp_path / "config.json")
    saved = tmp_path / "saved" / "blender.exe"
    start_menu = tmp_path / "start" / "blender.exe"
    path_blender = tmp_path / "path" / "blender.exe"
    saved.parent.mkdir()
    start_menu.parent.mkdir()
    path_blender.parent.mkdir()
    saved.write_text("", encoding="utf-8")
    start_menu.write_text("", encoding="utf-8")
    path_blender.write_text("", encoding="utf-8")
    store.save_blender_path(saved)

    locator = BlenderLocator(store)
    monkeypatch.setattr(locator, "is_valid_blender", lambda path: path == saved)
    monkeypatch.setattr(locator, "_start_menu_candidates", lambda: [start_menu])
    monkeypatch.setattr("assetforge.blender.locator.shutil.which", lambda _: str(path_blender))
    monkeypatch.setattr(locator, "_registry_candidates", lambda: [])
    monkeypatch.setattr(locator, "_steam_candidates", lambda: [])

    result = locator.locate()

    assert result is not None
    assert result.executable == saved.resolve()
    assert result.source == "saved configuration"


def test_locator_checks_start_menu_before_path(tmp_path: Path, monkeypatch) -> None:
    store = UserConfigStore(tmp_path / "config.json")
    start_menu = tmp_path / "start" / "blender.exe"
    path_blender = tmp_path / "path" / "blender.exe"
    start_menu.parent.mkdir()
    path_blender.parent.mkdir()
    start_menu.write_text("", encoding="utf-8")
    path_blender.write_text("", encoding="utf-8")

    locator = BlenderLocator(store)
    checked: list[Path] = []

    def fake_valid(path: Path) -> bool:
        checked.append(path)
        return path == start_menu

    monkeypatch.setattr(locator, "is_valid_blender", fake_valid)
    monkeypatch.setattr(locator, "_start_menu_candidates", lambda: [start_menu])
    monkeypatch.setattr("assetforge.blender.locator.shutil.which", lambda _: str(path_blender))
    monkeypatch.setattr(locator, "_registry_candidates", lambda: [])
    monkeypatch.setattr(locator, "_steam_candidates", lambda: [])

    result = locator.locate()

    assert result is not None
    assert result.executable == start_menu.resolve()
    assert result.source == "Start Menu shortcut"
    assert checked[0] == start_menu


def test_locator_does_not_scan_drives(monkeypatch, tmp_path: Path) -> None:
    store = UserConfigStore(tmp_path / "config.json")
    locator = BlenderLocator(store)

    monkeypatch.setattr(locator, "_start_menu_candidates", lambda: [])
    monkeypatch.setattr("assetforge.blender.locator.shutil.which", lambda _: None)
    monkeypatch.setattr(locator, "_registry_candidates", lambda: [])
    monkeypatch.setattr(locator, "_steam_candidates", lambda: [])

    assert locator.locate() is None


def test_manual_save_persists_path(tmp_path: Path) -> None:
    store = UserConfigStore(tmp_path / "config.json")
    blender = tmp_path / "blender.exe"

    store.save_blender_path(blender)

    assert store.saved_blender_path() == blender
