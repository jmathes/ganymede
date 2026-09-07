"""Command line: run a paper, resume a run, show status, or check a tarball."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from ganymede.config import Settings
from ganymede.state import Run


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader: KEY=VALUE lines, no expansion. Existing env vars win."""
    import os

    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip("'\"")
        if k.startswith("export "):
            k = k[7:].strip()
        os.environ.setdefault(k, v)


def _settings(args) -> Settings:
    s = Settings()
    if getattr(args, "runs_dir", None):
        s.runs_dir = Path(args.runs_dir)
    if getattr(args, "model", None):
        s.model = args.model
    if getattr(args, "no_referee", False):
        s.use_referee = False
    return s


def cmd_run(args) -> int:
    settings = _settings(args)
    run = Run(
        run_id=args.run_id or Run.new_id(),
        paper_path=str(Path(args.paper).resolve()),
        lean_project_dir=str(Path(args.lean_project).resolve()) if args.lean_project else None,
    )
    run.save(settings.runs_dir)
    print(f"run {run.run_id} created in {run.dir(settings.runs_dir)}")
    return _drive(run, settings)


def cmd_resume(args) -> int:
    settings = _settings(args)
    run = Run.load(settings.runs_dir, args.run_id)
    if run.status in ("done",):
        print(run.summary())
        return 0
    return _drive(run, settings)


def cmd_status(args) -> int:
    settings = _settings(args)
    if args.run_id:
        print(Run.load(settings.runs_dir, args.run_id).summary())
    else:
        for p in sorted(settings.runs_dir.glob("*/state.json")):
            print(Run.model_validate_json(p.read_text()).summary().splitlines()[0])
    return 0


def cmd_check(args) -> int:
    from ganymede.lean_check import inspect_directory, inspect_tarball, report_for_prompt

    p = Path(args.path)
    report = inspect_directory(p) if p.is_dir() else inspect_tarball(p)
    print(report_for_prompt(report))
    return 0 if report.clean else 1


def _drive(run: Run, settings: Settings) -> int:
    from ganymede.advisor import ClaudeAdvisor
    from ganymede.formalizer import AristotleFormalizer
    from ganymede.orchestrator import Orchestrator

    advisor = ClaudeAdvisor(settings, spend=run.spend, transcript_dir=run.dir(settings.runs_dir) / "transcripts")
    formalizer = AristotleFormalizer(project_id=run.aristotle_project_id)
    orch = Orchestrator(run, settings, advisor, formalizer)
    run = asyncio.run(orch.run_to_completion())
    print(run.summary())
    return 0 if run.status == "done" else 2


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    ap = argparse.ArgumentParser(prog="ganymede", description="Carry water between Claude and Aristotle.")
    ap.add_argument("--runs-dir", help="where run state lives (default: ./runs or $GANYMEDE_RUNS_DIR)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="verify a paper")
    p.add_argument("--paper", required=True, help="the paper (.tex, .md, .txt)")
    p.add_argument("--lean-project", help="existing Lean project dir to work in (optional)")
    p.add_argument("--run-id")
    p.add_argument("--model")
    p.add_argument("--no-referee", action="store_true")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("resume", help="continue a run after a crash or halt")
    p.add_argument("run_id")
    p.add_argument("--model")
    p.add_argument("--no-referee", action="store_true")
    p.set_defaults(fn=cmd_resume)

    p = sub.add_parser("status", help="show run status")
    p.add_argument("run_id", nargs="?")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("check", help="static done-check of a result tarball or Lean project dir")
    p.add_argument("path")
    p.set_defaults(fn=cmd_check)

    args = ap.parse_args(argv)
    sys.exit(args.fn(args))
