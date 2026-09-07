"""The loop (TODO steps 4, 6, 7, 8). Ganymede does no mathematics; it moves things between the
mathematician (Claude), the referee (Claude), and the formalizer (Aristotle), and enforces guards.

    plan -> for each ready slice:
              instructions -> Aristotle task -> (answer questions) -> tarball -> lean check -> grade
              accept | retry (more detail) | handoff (mathematician writes the route) | give_up
         -> final fidelity report -> DONE or HALTED
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from ganymede.advisor import Advisor, BudgetExceeded, SlicePlan, SliceSpec
from ganymede.config import Settings
from ganymede.formalizer import Formalizer
from ganymede.lean_check import inspect_directory, inspect_tarball, report_for_prompt
from ganymede.notify import notify
from ganymede.state import Attempt, Run, RunStatus, Slice, SliceStatus, now, write_json

log = logging.getLogger("ganymede")
TEMPLATE_PROJECT = Path(__file__).resolve().parent.parent / "templates" / "lean-project"


class Halt(Exception):
    """Stop the run and tell the human. Not an error in the code."""


class Orchestrator:
    def __init__(self, run: Run, settings: Settings, advisor: Advisor, formalizer: Formalizer):
        self.run = run
        self.settings = settings
        self.advisor = advisor
        self.formalizer = formalizer
        self.plan: SlicePlan | None = None
        self._started = time.monotonic()
        self.run_dir = run.dir(settings.runs_dir)
        self.plan_path = self.run_dir / "plan.json"
        if self.plan_path.exists():
            self.plan = SlicePlan.model_validate_json(self.plan_path.read_text())
        if formalizer.project_id is None and run.aristotle_project_id:
            formalizer.project_id = run.aristotle_project_id
        advisor.spend = run.spend  # one counter, persisted with the run

    # ---- entry points -------------------------------------------------------

    async def run_to_completion(self) -> Run:
        try:
            await self._main()
        except Halt as h:
            self._halt(str(h))
        except BudgetExceeded as b:
            self._halt(f"budget: {b}")
        except Exception as e:  # noqa: BLE001
            log.exception("unrecoverable error")
            self.run.status = RunStatus.FAILED
            self.run.halt_reason = f"{type(e).__name__}: {e}"
            self._save()
            notify(f"Ganymede run {self.run.run_id} FAILED: {self.run.halt_reason}", self.settings.notify_cmd)
        return self.run

    async def _main(self) -> None:
        if self.plan is None:
            self._plan()
        self.run.status = RunStatus.RUNNING
        self._save()

        while True:
            self._check_run_guards()
            slice_ = self.run.next_slice()
            if slice_ is None:
                break
            await self._work_slice(slice_)

        if not self.run.all_accepted():
            blocked = [s.id for s in self.run.slices if s.status == SliceStatus.BLOCKED]
            waiting = [s.id for s in self.run.slices if s.status == SliceStatus.PENDING]
            raise Halt(f"blocked slices: {blocked}; slices waiting on them: {waiting}")

        self._final_check()

    # ---- phases -------------------------------------------------------------

    def _plan(self) -> None:
        if not self.run.lean_project_dir:
            # No project supplied: start from the template pinned to the Mathlib version Aristotle supports.
            dest = self.run_dir / "project"
            if not dest.exists():
                shutil.copytree(TEMPLATE_PROJECT, dest)
            self.run.lean_project_dir = str(dest)
            self.run.log(f"created Lean project from template at {dest}", self.settings.runs_dir)
        paper = Path(self.run.paper_path).read_text(errors="replace")
        lean_report = None
        if self.run.lean_project_dir:
            lean_report = report_for_prompt(inspect_directory(self.run.lean_project_dir))
        self.plan = self.advisor.plan(paper, lean_report)
        self.plan_path.parent.mkdir(parents=True, exist_ok=True)
        self.plan_path.write_text(self.plan.model_dump_json(indent=2))
        self.run.slices = [
            Slice(id=s.id, title=s.title, goal=s.goal, lean_targets=s.lean_targets, depends_on=s.depends_on)
            for s in self.plan.slices
        ]
        self.run.log(f"planned {len(self.run.slices)} slices", self.settings.runs_dir)
        _say("PAPER SUMMARY", self.plan.paper_summary)
        _say("MAIN CLAIMS", "\n".join(f"- {c}" for c in self.plan.main_claims))
        for sl in self.run.slices:
            deps = f" (after {', '.join(sl.depends_on)})" if sl.depends_on else ""
            _say(f"SLICE {sl.id}{deps}: {sl.title}", sl.goal)

    async def _work_slice(self, slice_: Slice) -> None:
        spec = self._spec(slice_)
        slice_.status = SliceStatus.RUNNING
        # Resume: if the last attempt has a task but no decision, we crashed mid-attempt. Re-run grading path.
        while True:
            self._check_run_guards()
            attempt_no = len(slice_.attempts) + 1
            if attempt_no > self.settings.max_attempts_per_slice:
                slice_.status = SliceStatus.BLOCKED
                self.run.log(f"{slice_.id}: blocked after {attempt_no - 1} attempts", self.settings.runs_dir)
                return

            last = slice_.attempts[-1] if slice_.attempts else None
            if last and last.decision is None and last.aristotle_task_id:
                attempt = last  # resume a task we already submitted
                self.run.log(f"{slice_.id}: resuming attempt {attempt_no - 1} task {attempt.aristotle_task_id}", self.settings.runs_dir)
            else:
                attempt = self._new_attempt(spec, slice_, last)
                _say(f"INSTRUCTIONS TO ARISTOTLE for {slice_.id}, attempt {attempt_no}, detail level {attempt.detail_level}", attempt.prompt)
                self._check_task_guard()
                if self.formalizer.project_id is None:
                    lean_dir = Path(self.run.lean_project_dir) if self.run.lean_project_dir else None
                    attempt.aristotle_task_id = await self.formalizer.create(attempt.prompt, lean_dir)
                    self.run.aristotle_project_id = self.formalizer.project_id
                else:
                    attempt.aristotle_task_id = await self.formalizer.instruct(attempt.prompt)
                self.run.spend.aristotle_tasks += 1
                self._save()

            result = await self.formalizer.run(attempt.aristotle_task_id, self._question_handler(spec), self.settings.max_task_hours)
            attempt.task_status = result.status
            attempt.finished_at = now()
            self.run.log(f"{slice_.id}: task {result.task_id} ended {result.status}", self.settings.runs_dir)
            if result.summary:
                _say("ARISTOTLE'S SUMMARY", result.summary)

            if result.status in ("FAILED", "CANCELED"):
                attempt.decision = "retry"
                self.run.log(f"{slice_.id}: task {result.status}; retrying", self.settings.runs_dir)
                continue

            tarball = self.run_dir / "tarballs" / f"{slice_.id}-{attempt.aristotle_task_id}.tar.gz"
            tarball.parent.mkdir(parents=True, exist_ok=True)
            await self.formalizer.download(tarball)
            attempt.tarball = str(tarball)
            report = inspect_tarball(tarball)
            attempt.lean_report = report.model_dump()
            report_text = report_for_prompt(report)
            _say(f"LEAN CHECK of {tarball.name}", report_text)

            grade = self.advisor.grade(
                self.plan, spec, attempt.prompt, result.status, result.summary, report_text,
                attempt_no, self.settings.max_attempts_per_slice,
            )
            attempt.grade = grade.model_dump()
            attempt.decision = grade.decision
            self.run.log(f"{slice_.id}: attempt {attempt_no} graded {grade.decision} (fidelity {grade.statement_fidelity})", self.settings.runs_dir)
            _say("GRADE", f"decision: {grade.decision}\nfidelity: {grade.statement_fidelity}: {grade.fidelity_notes}\n{grade.reasoning}"
                 + (f"\nHANDOFF NOTES:\n{grade.handoff_notes}" if grade.handoff_notes else ""))

            if grade.decision == "accept":
                if not report.clean or grade.statement_fidelity != "matches":
                    # The mathematician (even after the referee) accepted something our static check rejects.
                    # Static checks win; downgrade to retry with a note.
                    attempt.decision = "retry"
                    slice_.handoff_notes = (slice_.handoff_notes or "") + (
                        f"\n\nAttempt {attempt_no} was accepted by the mathematician but the static check found: "
                        f"{report.brief()}; fidelity={grade.statement_fidelity}. Fix these."
                    )
                    self.run.log(f"{slice_.id}: accept overridden by static check ({report.brief()})", self.settings.runs_dir)
                    continue
                slice_.status = SliceStatus.ACCEPTED
                self._save()
                return
            if grade.decision == "give_up":
                slice_.status = SliceStatus.BLOCKED
                self._save()
                return
            if grade.decision == "handoff" and grade.handoff_notes:
                slice_.handoff_notes = ((slice_.handoff_notes or "") + "\n\n" + grade.handoff_notes).strip()
            self._save()

    def _new_attempt(self, spec: SliceSpec, slice_: Slice, last: Attempt | None) -> Attempt:
        if last is None:
            level = 0
        else:
            level = max(last.detail_level + 1, (last.grade or {}).get("next_detail_level", 0))
        history = "\n\n".join(
            f"attempt {i + 1} (detail {a.detail_level}): status {a.task_status}, decision {a.decision}\n"
            f"grade: {(a.grade or {}).get('reasoning', '')}\nlean: {_brief(a.lean_report)}"
            for i, a in enumerate(slice_.attempts)
        )
        instr = self.advisor.instructions(self.plan, spec, level, history, slice_.handoff_notes)
        attempt = Attempt(detail_level=instr.detail_level, prompt=instr.prompt)
        slice_.attempts.append(attempt)
        self._save()
        return attempt

    def _question_handler(self, spec: SliceSpec):
        async def handle(question: str, suggestions: list[str], recent: list[str]) -> str:
            _say("ARISTOTLE ASKS", question + ("\nsuggested: " + " | ".join(suggestions) if suggestions else ""))
            ans = self.advisor.answer(self.plan, spec, question, suggestions, "\n".join(recent))
            _say("ANSWER", ans.answer)
            self.run.log(f"{spec.id}: answered Aristotle: {question[:120]!r} -> {ans.answer[:120]!r}", self.settings.runs_dir)
            return ans.answer

        return handle

    def _final_check(self) -> None:
        self.run.status = RunStatus.VERIFYING
        self._save()
        last_tarball = None
        for s in self.run.slices:
            for a in s.attempts:
                if a.tarball:
                    last_tarball = a.tarball
        if last_tarball is None:
            raise Halt("no tarball to verify")
        report = inspect_tarball(last_tarball)
        final = self.advisor.final_report(self.plan, report_for_prompt(report))
        if not report.clean:
            final.verified = False
            final.caveats.append(f"static check: {report.brief()}")
        self.run.final_report = final.model_dump()
        write_json(self.run_dir / "final_report.json", final.model_dump())
        (self.run_dir / "REPORT.md").write_text(_render_report(self.run, final, report.brief()))
        _say("FINAL REPORT", f"verified: {final.verified}\n" + "\n".join(final.claim_status) + ("\ncaveats:\n" + "\n".join(final.caveats) if final.caveats else "") + f"\n{final.summary}")
        if final.verified:
            self.run.status = RunStatus.DONE
            self._save()
            notify(f"Ganymede run {self.run.run_id} DONE: verification is clean. See {self.run_dir / 'REPORT.md'}", self.settings.notify_cmd)
        else:
            raise Halt("final check not verified: " + "; ".join(final.caveats or [final.summary]))

    # ---- guards (TODO step 8) ---------------------------------------------

    def _check_run_guards(self) -> None:
        hours = (time.monotonic() - self._started) / 3600
        if hours > self.settings.max_run_hours:
            raise Halt(f"run exceeded {self.settings.max_run_hours} h")
        if self.run.spend.claude_calls >= self.settings.max_claude_calls:
            raise Halt(f"claude call budget {self.settings.max_claude_calls} reached")

    def _check_task_guard(self) -> None:
        if self.run.spend.aristotle_tasks >= self.settings.max_aristotle_tasks:
            raise Halt(f"aristotle task budget {self.settings.max_aristotle_tasks} reached")

    # ---- helpers ------------------------------------------------------------

    def _spec(self, s: Slice) -> SliceSpec:
        return SliceSpec(id=s.id, title=s.title, goal=s.goal, lean_targets=s.lean_targets, depends_on=s.depends_on)

    def _save(self) -> None:
        self.run.save(self.settings.runs_dir)

    def _halt(self, reason: str) -> None:
        self.run.status = RunStatus.HALTED
        self.run.halt_reason = reason
        self._save()
        notify(f"Ganymede run {self.run.run_id} HALTED: {reason}\n{self.run.summary()}", self.settings.notify_cmd)


def _say(title: str, body: str) -> None:
    """Everything the run records on disk that a person would want to see also goes to the terminal."""
    bar = "=" * 8
    log.info("%s %s %s\n%s", bar, title, bar, body.rstrip())


def _brief(report: dict | None) -> str:
    if not report:
        return "(none)"
    return f"{len(report.get('sorries', []))} sorries, {len(report.get('axioms', []))} axioms, {len(report.get('theorems', []))} theorems"


def _render_report(run: Run, final, static_brief: str) -> str:
    lines = [f"# Ganymede report for run {run.run_id}", ""]
    lines.append(f"**Verified:** {'yes' if final.verified else 'no'}  ")
    lines.append(f"**Static check:** {static_brief}  ")
    lines.append(f"**Aristotle project:** {run.aristotle_project_id}  ")
    lines.append(f"**Spend:** {run.spend.claude_calls} Claude calls ({run.spend.claude_input_tokens} in / {run.spend.claude_output_tokens} out), {run.spend.aristotle_tasks} Aristotle tasks")
    lines += ["", "## Summary", "", final.summary, "", "## Claims", ""]
    lines += [f"- {c}" for c in final.claim_status]
    if final.caveats:
        lines += ["", "## Caveats", ""] + [f"- {c}" for c in final.caveats]
    lines += ["", "## Slices", ""]
    for s in run.slices:
        lines.append(f"- **{s.id}** {s.title}: {s.status}, {len(s.attempts)} attempts")
    return "\n".join(lines) + "\n"
