"""Start tamadesk at login on Linux (systemd user service), macOS (launch agent) or Windows (Startup
folder), so reminders ring without a terminal open. `tamadesk install-service` writes the file and
turns it on; `--dry-run` only shows what it would do.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

LINUX_UNIT = """# written by `tamadesk install-service`
[Unit]
Description=tamadesk (desk companion: API + UI + reminders)
After=network-online.target

[Service]
Type=simple
# your shell's PATH at install time, so it finds claude, mcporter and notify-send like you do
Environment=PATH={path}
ExecStart={python} -m tamadesk serve
Restart=on-failure
SuccessExitStatus=143
RestartSec=5

[Install]
WantedBy=default.target
"""

MAC_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>dev.tamadesk</string>
  <key>ProgramArguments</key><array><string>{python}</string><string>-m</string><string>tamadesk</string>
    <string>serve</string></array>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>{path}</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
</dict></plist>
"""

# a .vbs so it starts without a console window; pythonw has none either
WIN_VBS = 'CreateObject("WScript.Shell").Run """{python}"" -m tamadesk serve", 0, False\n'


def plan(platform: str | None = None, home: Path | None = None) -> tuple[Path, str, list[list[str]]]:
    """(file to write, its contents, commands that turn it on) for this computer."""
    platform = platform or sys.platform
    home = home or Path.home()
    python, path = sys.executable, os.environ.get("PATH", "")
    if platform.startswith("linux"):
        return (home / ".config/systemd/user/tamadesk.service", LINUX_UNIT.format(path=path, python=python),
                [["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", "tamadesk"]])  # fmt: skip
    if platform == "darwin":
        f = home / "Library/LaunchAgents/dev.tamadesk.plist"
        return f, MAC_PLIST.format(path=path, python=python), [["launchctl", "load", "-w", str(f)]]
    if platform.startswith("win"):
        pythonw = str(Path(python).with_name("pythonw.exe"))
        startup = home / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
        return startup / "tamadesk.vbs", WIN_VBS.format(python=pythonw), []
    raise RuntimeError(f"don't know how to start at login on {platform}; run `tamadesk serve` yourself")
