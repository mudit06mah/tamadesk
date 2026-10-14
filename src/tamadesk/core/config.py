"""Settings live in the user's data folder (not the repo), so an installed tamadesk works anywhere.

Linux: ~/.local/share/tamadesk, macOS: ~/Library/Application Support/tamadesk,
Windows: %LOCALAPPDATA%\\tamadesk. Override with TAMADESK_HOME.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from platformdirs import user_data_path
from pydantic import BaseModel, Field

BrainKind = Literal["claude_code", "ollama"]


def home_dir() -> Path:
    """The data folder: $TAMADESK_HOME, or the OS's user data dir (~/.local/share/tamadesk on Linux)."""
    if env := os.environ.get("TAMADESK_HOME"):
        return Path(env).expanduser().resolve()
    return user_data_path("tamadesk", appauthor=False)


class ServerCfg(BaseModel):
    host: str = "127.0.0.1"
    port: int = 6206


class BrainCfg(BaseModel):
    kind: BrainKind = "claude_code"
    model: str = "sonnet"  # claude_code: sonnet|opus|haiku; ollama: any pulled model
    light_model: str = "haiku"  # claude_code only: summaries and other tiny text jobs
    light_usd: float = 0.05  # --max-budget-usd for one light call
    ollama_url: str = "http://127.0.0.1:11434"
    timeout_s: int = 180


class AssistantCfg(BaseModel):
    model: str = "sonnet"  # the "ask" agent; light jobs use brain.light_model
    effort: str = "medium"  # low | medium | high
    max_usd_per_ask: float = 0.50  # Claude Code's --max-budget-usd for one request
    daily_usd: float = 3.00  # asks stop for the day past this (usage is API-equivalent dollars)
    reach_servers: list[str] = ["exa"]  # agent-reach MCP servers to plug in (login-free only)


class MailCfg(BaseModel):
    address: str = ""  # your address; the app password lives in <home>/secrets.json (0600)
    provider: str = "gmail"  # gmail|fastmail|icloud|outlook|yahoo|zoho|custom (see life/mail.PROVIDERS)
    imap_host: str = ""  # only for custom
    smtp_host: str = ""
    smtp_port: int = 465  # 465 = SSL; 587 = STARTTLS
    from_name: str = ""
    dry_run: bool = True  # everything goes to your own address until switched off
    daily_cap: int = 20


HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class DayCfg(BaseModel):
    """The user's day: it runs from when they wake to when they go to bed, and the recap comes at bedtime."""

    wake: str = Field(default="08:00", pattern=HHMM)  # usual wake-up time, local
    bed: str = Field(
        default="", pattern=rf"{HHMM}|^$"
    )  # usual bedtime, local ('' = recap_hour, older configs)
    recap_hour: int = 21  # before wake/bed existed: the recap hour (still read when `bed` is empty)
    todo_goal: int = 3  # todos per day that count as a "good day"
    quiet_start: int | None = None  # local hour quiet hours begin (e.g. 22); non-urgent pings wait
    quiet_end: int | None = None  # local hour they end (e.g. 8)

    @property
    def bed_at(self) -> str:
        """Bedtime as 'HH:MM': when the recap is written."""
        return self.bed or f"{self.recap_hour:02d}:00"


class CalendarCfg(BaseModel):
    from_mail: bool = True  # read calendar invites in the inbox it already checks (event fields only)
    remind_min: int = 10  # ring this many minutes before a meeting (0 = when it starts)


class Settings(BaseModel):
    """Everything in config.yaml. Secrets (mail password, calendar feed) live in secrets.json instead."""

    home: Path
    server: ServerCfg = ServerCfg()
    brain: BrainCfg = BrainCfg()
    day: DayCfg = DayCfg()
    assistant: AssistantCfg = AssistantCfg()
    mail: MailCfg = MailCfg()
    calendar: CalendarCfg = CalendarCfg()

    @property
    def db_path(self) -> Path:
        return self.home / "tamadesk.db"

    @property
    def config_path(self) -> Path:
        return self.home / "config.yaml"


def load_settings(home: Path | None = None) -> Settings:
    """Read config.yaml from the data folder, writing a default one on first run."""
    home = home or home_dir()
    home.mkdir(parents=True, exist_ok=True)
    path = home / "config.yaml"
    raw = (yaml.safe_load(path.read_text()) or {}) if path.is_file() else {}
    s = Settings(home=home, **raw)
    if not path.is_file():
        save_settings(s)
    return s


def save_settings(s: Settings) -> None:
    """Write the settings back to config.yaml."""
    data = s.model_dump(mode="json", exclude={"home"})
    s.config_path.write_text("# tamadesk settings (editable here or in the app)\n" + yaml.safe_dump(data))


@lru_cache
def get_settings() -> Settings:
    """The settings, loaded once per process (tests clear the cache to switch folders)."""
    return load_settings()
