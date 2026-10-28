"""Find the bridge URL and token: RIMCP_URL / RIMCP_TOKEN, else RimMCP's saved mod settings."""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORT = 39571

# RimWorld names a mod's settings file Mod_<mod folder>_<Mod class>.xml; RimMCP's class is RiMCPMod.
SETTINGS_GLOB = "Mod_*_RiMCPMod.xml"


@dataclass(frozen=True)
class BridgeConfig:
    url: str
    token: str | None
    source: str


def rimworld_config_dirs() -> list[Path]:
    home = Path.home()
    unity = Path("unity3d") / "Ludeon Studios" / "RimWorld by Ludeon Studios" / "Config"
    candidates = [home / ".config" / unity]
    # Flatpak Steam keeps its own XDG config dir.
    candidates.append(home / ".var" / "app" / "com.valvesoftware.Steam" / ".config" / unity)
    if sys.platform == "darwin":
        candidates.append(home / "Library" / "Application Support" / "RimWorld" / "Config")
    if sys.platform == "win32":
        candidates.append(home / "AppData" / "LocalLow" / "Ludeon Studios" / "RimWorld by Ludeon Studios" / "Config")
    return [path for path in candidates if path.is_dir()]


def read_settings_file(path: Path) -> tuple[int, str | None]:
    root = ET.parse(path).getroot()
    port_text = root.findtext(".//port")
    token = root.findtext(".//token")
    port = int(port_text) if port_text and port_text.strip().isdigit() else DEFAULT_PORT
    return port, (token.strip() or None) if token else None


def discover(config_dirs: list[Path] | None = None) -> BridgeConfig:
    url = os.environ.get("RIMCP_URL")
    token = os.environ.get("RIMCP_TOKEN")
    if url and token:
        return BridgeConfig(url.rstrip("/"), token, "environment")

    dirs = rimworld_config_dirs() if config_dirs is None else config_dirs
    # Newest first: a Workshop copy and a local copy can each leave a settings file behind.
    files = sorted((f for d in dirs for f in d.glob(SETTINGS_GLOB)), key=lambda f: f.stat().st_mtime, reverse=True)
    for settings in files:
        try:
            port, saved_token = read_settings_file(settings)
        except (ET.ParseError, OSError):
            continue
        return BridgeConfig(
            (url or f"http://127.0.0.1:{port}").rstrip("/"),
            token or saved_token,
            str(settings),
        )

    return BridgeConfig((url or f"http://127.0.0.1:{DEFAULT_PORT}").rstrip("/"), token, "default")
