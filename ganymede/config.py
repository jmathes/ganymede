"""Run settings. Everything has a default; env vars override; CLI flags override those."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


@dataclass
class Settings:
    # Claude. Backend "cli" shells out to `claude -p` and uses the Claude Code login (subscription);
    # "api" uses the Anthropic SDK with ANTHROPIC_API_KEY; "auto" picks api if that key is set, else cli.
    claude_backend: str = field(default_factory=lambda: os.environ.get("GANYMEDE_CLAUDE_BACKEND", "auto"))
    model: str = field(default_factory=lambda: os.environ.get("GANYMEDE_MODEL", "claude-opus-5"))
    effort: str = field(default_factory=lambda: os.environ.get("GANYMEDE_EFFORT", "high"))
    max_tokens: int = field(default_factory=lambda: _env_int("GANYMEDE_MAX_TOKENS", 16000))
    claude_timeout_s: float = field(default_factory=lambda: _env_float("GANYMEDE_CLAUDE_TIMEOUT", 1800))
    use_referee: bool = field(default_factory=lambda: os.environ.get("GANYMEDE_REFEREE", "1") != "0")

    # Guards (TODO step 8)
    max_attempts_per_slice: int = field(default_factory=lambda: _env_int("GANYMEDE_MAX_ATTEMPTS", 4))
    max_aristotle_tasks: int = field(default_factory=lambda: _env_int("GANYMEDE_MAX_TASKS", 40))
    max_claude_calls: int = field(default_factory=lambda: _env_int("GANYMEDE_MAX_CLAUDE_CALLS", 200))
    max_task_hours: float = field(default_factory=lambda: _env_float("GANYMEDE_MAX_TASK_HOURS", 10))
    max_run_hours: float = field(default_factory=lambda: _env_float("GANYMEDE_MAX_RUN_HOURS", 72))

    # Run `lake build` in the Lean project before the first upload so Aristotle gets its dependencies.
    lake_build: bool = field(default_factory=lambda: os.environ.get("GANYMEDE_LAKE_BUILD", "1") != "0")

    # Rebuild every Aristotle result with the local Lean toolchain and print its axioms (needs elan).
    local_build: bool = field(default_factory=lambda: os.environ.get("GANYMEDE_LOCAL_BUILD", "1") != "0")
    local_build_timeout_s: float = field(default_factory=lambda: _env_float("GANYMEDE_LOCAL_BUILD_TIMEOUT", 3600))

    # Where run state lives
    runs_dir: Path = field(default_factory=lambda: Path(os.environ.get("GANYMEDE_RUNS_DIR", "runs")))

    # Optional shell command run on halt/finish; receives the message on stdin.
    notify_cmd: str | None = field(default_factory=lambda: os.environ.get("GANYMEDE_NOTIFY_CMD"))
