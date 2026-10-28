import os
import time

from rimsdk import config

SETTINGS = """<?xml version="1.0" encoding="utf-8"?>
<SettingsBlock>
  <ModSettings Class="RiMCP.Settings.RiMCPSettings">
    <port>{port}</port>
    <token>{token}</token>
  </ModSettings>
</SettingsBlock>
"""


def write(dirpath, name, port, token):
    path = dirpath / name
    path.write_text(SETTINGS.format(port=port, token=token))
    return path


def test_env_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("RIMCP_URL", "http://127.0.0.1:1234/")
    monkeypatch.setenv("RIMCP_TOKEN", "envtoken")
    write(tmp_path, "Mod_3809698070_RiMCPMod.xml", 5555, "filetoken")
    found = config.discover([tmp_path])
    assert (found.url, found.token, found.source) == ("http://127.0.0.1:1234", "envtoken", "environment")


def test_reads_newest_settings_file(monkeypatch, tmp_path):
    monkeypatch.delenv("RIMCP_URL", raising=False)
    monkeypatch.delenv("RIMCP_TOKEN", raising=False)
    old = write(tmp_path, "Mod_rimcp_RiMCPMod.xml", 1111, "old")
    os.utime(old, (time.time() - 100, time.time() - 100))
    write(tmp_path, "Mod_3809698070_RiMCPMod.xml", 2222, "new")
    write(tmp_path, "Mod_other_OtherMod.xml", 3333, "nope")
    found = config.discover([tmp_path])
    assert (found.url, found.token) == ("http://127.0.0.1:2222", "new")


def test_defaults_without_settings(monkeypatch, tmp_path):
    monkeypatch.delenv("RIMCP_URL", raising=False)
    monkeypatch.delenv("RIMCP_TOKEN", raising=False)
    found = config.discover([tmp_path])
    assert (found.url, found.token, found.source) == ("http://127.0.0.1:39571", None, "default")
