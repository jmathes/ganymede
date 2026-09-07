"""Persistent run state (TODO step 5). One JSON file per run, rewritten atomically after every step."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

log = logging.getLogger("ganymede")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SliceStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    ACCEPTED = "accepted"
    BLOCKED = "blocked"      # gave up after max attempts


class RunStatus(StrEnum):
    PLANNING = "planning"
    RUNNING = "running"
    VERIFYING = "verifying"  # all slices accepted; final fidelity check pending
    DONE = "done"            # bullet-proof by our definition of done
    HALTED = "halted"        # guard tripped or blocked slice; needs a human
    FAILED = "failed"        # unrecoverable error


class Attempt(BaseModel):
    started_at: str = Field(default_factory=now)
    finished_at: str | None = None
    detail_level: int = 0            # 0 = terse, higher = more spelled out
    prompt: str
    aristotle_task_id: str | None = None
    task_status: str | None = None
    tarball: str | None = None
    lean_report: dict | None = None
    local_build: dict | None = None
    grade: dict | None = None
    decision: str | None = None      # accept | retry | handoff | give_up


class Slice(BaseModel):
    id: str
    title: str
    goal: str                        # what must be proved, in words
    lean_targets: list[str] = []     # declaration names expected in the Lean project
    depends_on: list[str] = []
    status: SliceStatus = SliceStatus.PENDING
    attempts: list[Attempt] = []
    handoff_notes: str | None = None # accumulated detailed guidance from the mathematician


class Spend(BaseModel):
    claude_calls: int = 0
    claude_input_tokens: int = 0
    claude_output_tokens: int = 0
    aristotle_tasks: int = 0


class Run(BaseModel):
    run_id: str
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    status: RunStatus = RunStatus.PLANNING
    paper_path: str
    lean_project_dir: str | None = None
    aristotle_project_id: str | None = None
    slices: list[Slice] = []
    spend: Spend = Field(default_factory=Spend)
    halt_reason: str | None = None
    final_report: dict | None = None
    notes: list[str] = []

    # ---- persistence -------------------------------------------------------

    @staticmethod
    def new_id() -> str:
        return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]

    @classmethod
    def path_for(cls, runs_dir: Path, run_id: str) -> Path:
        return runs_dir / run_id / "state.json"

    @classmethod
    def load(cls, runs_dir: Path, run_id: str) -> "Run":
        return cls.model_validate_json(cls.path_for(runs_dir, run_id).read_text())

    def dir(self, runs_dir: Path) -> Path:
        return runs_dir / self.run_id

    def save(self, runs_dir: Path) -> None:
        self.updated_at = now()
        path = self.path_for(runs_dir, self.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(self.model_dump_json(indent=2))
        os.replace(tmp, path)

    def log(self, msg: str, runs_dir: Path | None = None) -> None:
        log.info(msg)
        self.notes.append(f"{now()} {msg}")
        if runs_dir is not None:
            self.save(runs_dir)

    # ---- queries -----------------------------------------------------------

    def slice(self, slice_id: str) -> Slice:
        for s in self.slices:
            if s.id == slice_id:
                return s
        raise KeyError(slice_id)

    def next_slice(self) -> Slice | None:
        """First pending slice whose dependencies are all accepted."""
        accepted = {s.id for s in self.slices if s.status == SliceStatus.ACCEPTED}
        for s in self.slices:
            if s.status in (SliceStatus.PENDING, SliceStatus.RUNNING) and set(s.depends_on) <= accepted:
                return s
        return None

    def all_accepted(self) -> bool:
        return bool(self.slices) and all(s.status == SliceStatus.ACCEPTED for s in self.slices)

    def summary(self) -> str:
        lines = [f"run {self.run_id}: {self.status}"]
        if self.halt_reason:
            lines.append(f"  halt reason: {self.halt_reason}")
        lines.append(f"  aristotle project: {self.aristotle_project_id}")
        lines.append(f"  spend: {self.spend.claude_calls} claude calls, {self.spend.aristotle_tasks} aristotle tasks")
        for s in self.slices:
            lines.append(f"  [{s.status:8}] {s.id}: {s.title} ({len(s.attempts)} attempts)")
        return "\n".join(lines)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
