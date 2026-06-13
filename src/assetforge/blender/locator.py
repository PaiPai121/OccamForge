from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from assetforge.core.config import UserConfigStore

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BlenderDiscoveryResult:
    executable: Path
    source: str


class BlenderLocator:
    """Finds and validates Blender without expensive drive scans."""

    def __init__(
        self,
        config_store: UserConfigStore,
        explicit_executable: Path | None = None,
        validation_timeout_seconds: int = 5,
    ) -> None:
        self._config_store = config_store
        self._explicit_executable = explicit_executable
        self._validation_timeout_seconds = validation_timeout_seconds

    def locate(self) -> BlenderDiscoveryResult | None:
        for candidate, source in self._candidate_paths():
            if self.is_valid_blender(candidate):
                resolved = candidate.resolve()
                self._config_store.save_blender_path(resolved)
                LOGGER.info("Using Blender from %s: %s", source, resolved)
                return BlenderDiscoveryResult(executable=resolved, source=source)
        return None

    def is_valid_blender(self, executable: Path) -> bool:
        if not executable.exists() or executable.name.lower() != "blender.exe":
            return False
        try:
            completed = subprocess.run(
                [str(executable), "--version"],
                capture_output=True,
                text=True,
                timeout=self._validation_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        output = f"{completed.stdout}\n{completed.stderr}".lower()
        return completed.returncode == 0 and "blender" in output

    def _candidate_paths(self) -> list[tuple[Path, str]]:
        candidates: list[tuple[Path, str]] = []
        saved = self._config_store.saved_blender_path()
        if saved is not None:
            candidates.append((saved, "saved configuration"))

        candidates.extend((path, "Start Menu shortcut") for path in self._start_menu_candidates())

        discovered = shutil.which("blender") or shutil.which("blender.exe")
        if discovered:
            candidates.append((Path(discovered), "PATH"))

        candidates.extend((path, "Windows Registry") for path in self._registry_candidates())
        candidates.extend((path, "Steam library") for path in self._steam_candidates())

        # Environment variable remains an explicit developer override, but it does not slow startup.
        if self._explicit_executable is not None:
            candidates.append((self._explicit_executable, "environment override"))

        return self._dedupe(candidates)

    def _start_menu_candidates(self) -> list[Path]:
        roots = [
            Path(os.getenv("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
            Path(os.getenv("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        ]
        shortcuts: list[Path] = []
        for root in roots:
            if root.exists():
                shortcuts.extend(
                    path
                    for path in root.rglob("*.lnk")
                    if "blender" in path.name.lower() or "blender" in str(path.parent).lower()
                )
        return [target for target in self._resolve_shortcuts(shortcuts) if target.name.lower() == "blender.exe"]

    def _resolve_shortcuts(self, shortcuts: list[Path]) -> list[Path]:
        if not shortcuts or sys.platform != "win32":
            return []
        script = "\n".join(
            [
                "$shell = New-Object -ComObject WScript.Shell",
                "$paths = @(",
                *[f"  {self._powershell_quote(str(path))}" for path in shortcuts],
                ")",
                "foreach ($path in $paths) {",
                "  try { $target = $shell.CreateShortcut($path).TargetPath; if ($target) { $target } } catch {}",
                "}",
            ]
        )
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if completed.returncode != 0:
            return []
        return [Path(line.strip()) for line in completed.stdout.splitlines() if line.strip()]

    def _registry_candidates(self) -> list[Path]:
        if sys.platform != "win32":
            return []
        try:
            import winreg
        except ImportError:
            return []

        candidates: list[Path] = []
        uninstall_roots = [
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        for hive, key_path in uninstall_roots:
            try:
                with winreg.OpenKey(hive, key_path) as root_key:
                    for index in range(winreg.QueryInfoKey(root_key)[0]):
                        self._collect_registry_uninstall_candidate(winreg, root_key, index, candidates)
            except OSError:
                continue
        return candidates

    def _collect_registry_uninstall_candidate(self, winreg: object, root_key: object, index: int, candidates: list[Path]) -> None:
        try:
            subkey_name = winreg.EnumKey(root_key, index)
            with winreg.OpenKey(root_key, subkey_name) as subkey:
                display_name = self._registry_value(winreg, subkey, "DisplayName")
                if "blender" not in display_name.lower():
                    return
                install_location = self._registry_value(winreg, subkey, "InstallLocation")
                display_icon = self._registry_value(winreg, subkey, "DisplayIcon")
        except OSError:
            return

        if install_location:
            candidates.append(Path(install_location) / "blender.exe")
        if display_icon:
            icon_path = display_icon.split(",", 1)[0].strip('"')
            candidates.append(Path(icon_path))

    def _registry_value(self, winreg: object, key: object, name: str) -> str:
        try:
            value, _ = winreg.QueryValueEx(key, name)
        except OSError:
            return ""
        return str(value)

    def _steam_candidates(self) -> list[Path]:
        steam_roots = self._steam_roots()
        library_roots: list[Path] = []
        for steam_root in steam_roots:
            if not steam_root.exists():
                continue
            library_roots.append(steam_root)
            library_roots.extend(self._parse_steam_libraries(steam_root / "steamapps" / "libraryfolders.vdf"))

        candidates: list[Path] = []
        for library_root in self._dedupe_paths(library_roots):
            candidates.extend(
                [
                    library_root / "steamapps" / "common" / "Blender" / "blender.exe",
                    library_root / "steamapps" / "common" / "Blender 4.0" / "blender.exe",
                    library_root / "steamapps" / "common" / "Blender 4.1" / "blender.exe",
                    library_root / "steamapps" / "common" / "Blender 4.2" / "blender.exe",
                    library_root / "steamapps" / "common" / "Blender 4.3" / "blender.exe",
                    library_root / "steamapps" / "common" / "Blender 4.4" / "blender.exe",
                ]
            )
        return candidates

    def _steam_roots(self) -> list[Path]:
        roots = [
            Path(os.getenv("PROGRAMFILES(X86)", "")) / "Steam",
            Path(os.getenv("PROGRAMFILES", "")) / "Steam",
        ]
        if sys.platform == "win32":
            try:
                import winreg

                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                    steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
                    roots.append(Path(str(steam_path)))
            except OSError:
                pass
        return roots

    def _parse_steam_libraries(self, library_file: Path) -> list[Path]:
        if not library_file.exists():
            return []
        try:
            text = library_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return []
        paths = re.findall(r'"path"\s+"([^"]+)"', text)
        return [Path(path.replace("\\\\", "\\")) for path in paths]

    def _dedupe(self, candidates: list[tuple[Path, str]]) -> list[tuple[Path, str]]:
        seen: set[str] = set()
        unique: list[tuple[Path, str]] = []
        for path, source in candidates:
            key = str(path).lower()
            if key not in seen:
                seen.add(key)
                unique.append((path, source))
        return unique

    def _dedupe_paths(self, paths: list[Path]) -> list[Path]:
        return [path for path, _ in self._dedupe([(path, "") for path in paths])]

    def _powershell_quote(self, value: str) -> str:
        return "'" + value.replace("'", "''") + "'"
