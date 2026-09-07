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


def cmd_doctor(args) -> int:
    """Check every prerequisite and say what to fix. Exit 0 only if a run could start."""
    import asyncio
    import os
    import shutil

    settings = _settings(args)
    ok = True

    def report(good: bool, what: str, fix: str = "") -> None:
        nonlocal ok
        ok = ok and good
        print(f"  [{'ok' if good else 'FAIL'}] {what}" + (f"\n         -> {fix}" if not good and fix else ""))

    print("Aristotle")
    key = os.environ.get("ARISTOTLE_API_KEY")
    report(bool(key), "ARISTOTLE_API_KEY is set", "create a key at https://aristotle.harmonic.fun/dashboard/keys and put it in .env")
    if key:
        try:
            from aristotlelib import Project

            asyncio.run(Project.list_projects(limit=1))
            report(True, "Aristotle accepts the key")
        except Exception as e:  # noqa: BLE001
            report(False, "Aristotle accepts the key", f"the server rejected it ({str(e)[:120]}); re-copy the key from the dashboard")

    print("Claude")
    backend = settings.claude_backend
    if backend == "auto":
        backend = "api" if os.environ.get("ANTHROPIC_API_KEY") else "cli"
    print(f"  backend: {backend}")
    if backend == "cli":
        report(shutil.which("claude") is not None, "`claude` command is installed", "install Claude Code: https://code.claude.com/docs/en/setup")
        if shutil.which("claude"):
            try:
                from ganymede.advisor import Answer, ClaudeCodeAdvisor, SlicePlan, SliceSpec

                probe = Settings(model="haiku", effort="low", use_referee=False, claude_timeout_s=180)
                adv = ClaudeCodeAdvisor(probe)
                out = adv._invoke("Answer in the requested JSON.", "Reply with answer='ok' and reasoning='probe'.", Answer, "doctor")[0]
                report(isinstance(out, Answer), "`claude -p` answers with structured output (uses your Claude login)")
            except Exception as e:  # noqa: BLE001
                report(False, "`claude -p` answers with structured output", f"{str(e)[:200]}; run `claude` once interactively and log in")
    else:
        try:
            import anthropic

            anthropic.Anthropic().models.retrieve(settings.model)
            report(True, f"Anthropic API key works and model {settings.model} exists")
        except Exception as e:  # noqa: BLE001
            report(False, "Anthropic API key works", str(e)[:200])

    print("Lean")
    lake = shutil.which("lake") or str(Path.home() / ".elan" / "bin" / "lake")
    has_lake = Path(lake).exists()
    report(has_lake, "lake (Lean build tool) is installed", "install elan: curl https://elan.lean-lang.org/elan-init.sh -sSf | sh   (or set GANYMEDE_LOCAL_BUILD=0 to skip local rebuilds)")

    print("Project")
    from ganymede.orchestrator import TEMPLATE_PROJECT

    report((TEMPLATE_PROJECT / "lakefile.toml").exists(), f"template Lean project at {TEMPLATE_PROJECT}")
    report(True, f"runs will be stored in {settings.runs_dir.resolve()}")
    print("\nAll good: run `ganymede run --paper <file>`" if ok else "\nFix the FAIL lines above, then run `ganymede doctor` again.")
    return 0 if ok else 1


def _drive(run: Run, settings: Settings) -> int:
    from ganymede.advisor import make_advisor
    from ganymede.formalizer import AristotleFormalizer
    from ganymede.orchestrator import Orchestrator

    advisor = make_advisor(settings, spend=run.spend, transcript_dir=run.dir(settings.runs_dir) / "transcripts")
    formalizer = AristotleFormalizer(project_id=run.aristotle_project_id)
    orch = Orchestrator(run, settings, advisor, formalizer)
    run = asyncio.run(orch.run_to_completion())
    print(run.summary())
    return 0 if run.status == "done" else 2


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "httpcore", "httpcore2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

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

    p = sub.add_parser("doctor", help="check keys, Claude, Lean, and the template; say what to fix")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("check", help="static done-check of a result tarball or Lean project dir")
    p.add_argument("path")
    p.set_defaults(fn=cmd_check)

    args = ap.parse_args(argv)
    sys.exit(args.fn(args))
