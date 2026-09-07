"""The Claude side: a mathematician role and a referee role, each a structured call (TODO steps 4, 6, 7).

Everything returns pydantic models so the orchestrator never parses prose. The referee, when
enabled, sees the mathematician's proposed judgment and may override it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from ganymede.config import Settings
from ganymede.state import Spend

log = logging.getLogger("ganymede.advisor")
PROMPTS = Path(__file__).parent / "prompts"

Decision = Literal["accept", "retry", "handoff", "give_up"]


# ---- structured outputs ----------------------------------------------------

class SliceSpec(BaseModel):
    id: str = Field(description="short slug, e.g. s1_lemma_bound")
    title: str
    goal: str = Field(description="what must be proved, in words, precisely")
    lean_targets: list[str] = Field(default_factory=list, description="Lean declaration names to create or fill")
    depends_on: list[str] = Field(default_factory=list, description="ids of slices that must be accepted first")


class SlicePlan(BaseModel):
    paper_summary: str
    main_claims: list[str] = Field(description="the paper's main theorems, stated precisely in words")
    slices: list[SliceSpec]


class Instructions(BaseModel):
    detail_level: int
    prompt: str = Field(description="the complete instruction text to send to Aristotle")


class Grade(BaseModel):
    decision: Decision
    statement_fidelity: Literal["matches", "differs", "unclear"]
    fidelity_notes: str = Field(description="how the Lean statements compare to the slice goal and paper claims")
    reasoning: str
    next_detail_level: int = Field(description="detail level to use if retrying or handing off")
    handoff_notes: str | None = Field(default=None, description="if handoff: the detailed mathematical guidance for Aristotle")


class Answer(BaseModel):
    answer: str = Field(description="the reply to send to Aristotle, self-contained")
    reasoning: str


class FinalReport(BaseModel):
    verified: bool = Field(description="true only if every main claim is established by a clean Lean theorem whose statement matches")
    claim_status: list[str] = Field(description="one line per main claim: matched theorem name and any discrepancy")
    caveats: list[str]
    summary: str


class RefereeVerdict(BaseModel):
    agrees: bool
    objection: str | None = None
    corrected_decision: Decision | None = None
    corrected_fidelity: Literal["matches", "differs", "unclear"] | None = None


# ---- protocol --------------------------------------------------------------

class Advisor(Protocol):
    spend: Spend

    def plan(self, paper: str, lean_report: str | None) -> SlicePlan: ...
    def instructions(self, plan: SlicePlan, slice_: SliceSpec, detail_level: int, history: str, handoff_notes: str | None) -> Instructions: ...
    def grade(self, plan: SlicePlan, slice_: SliceSpec, attempt_prompt: str, task_status: str, task_summary: str | None, lean_report: str, attempt_no: int, max_attempts: int) -> Grade: ...
    def answer(self, plan: SlicePlan, slice_: SliceSpec, question: str, suggestions: list[str], recent_events: str) -> Answer: ...
    def final_report(self, plan: SlicePlan, lean_report: str) -> FinalReport: ...


# ---- Claude implementation --------------------------------------------------

class ClaudeAdvisor:
    def __init__(self, settings: Settings, spend: Spend | None = None, transcript_dir: Path | None = None):
        import anthropic  # imported here so tests with the fake never need the SDK configured

        self.settings = settings
        self.spend = spend if spend is not None else Spend()
        self.transcript_dir = transcript_dir
        self.client = anthropic.Anthropic(timeout=settings.claude_timeout_s, max_retries=3)
        self.mathematician = (PROMPTS / "mathematician.md").read_text()
        self.referee = (PROMPTS / "referee.md").read_text()

    def _call(self, system: str, user: str, schema: type[BaseModel], tag: str):
        if self.spend.claude_calls >= self.settings.max_claude_calls:
            raise BudgetExceeded(f"claude call budget of {self.settings.max_claude_calls} reached")
        self.spend.claude_calls += 1
        response = self.client.messages.parse(
            model=self.settings.model,
            max_tokens=self.settings.max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": self.settings.effort},
            output_format=schema,
        )
        self.spend.claude_input_tokens += response.usage.input_tokens
        self.spend.claude_output_tokens += response.usage.output_tokens
        if response.stop_reason == "refusal":
            raise AdvisorError(f"Claude refused ({tag}): {getattr(response.stop_details, 'explanation', '')}")
        if response.parsed_output is None:
            raise AdvisorError(f"Claude returned no parsable output ({tag}), stop_reason={response.stop_reason}")
        self._transcribe(tag, user, response.parsed_output)
        return response.parsed_output

    def _transcribe(self, tag: str, user: str, out: BaseModel) -> None:
        if not self.transcript_dir:
            return
        self.transcript_dir.mkdir(parents=True, exist_ok=True)
        n = self.spend.claude_calls
        (self.transcript_dir / f"{n:04d}-{tag}.md").write_text(
            f"# {tag}\n\n## prompt\n\n{user}\n\n## response\n\n```json\n{out.model_dump_json(indent=2)}\n```\n"
        )

    # -- roles ----------------------------------------------------------------

    def plan(self, paper: str, lean_report: str | None) -> SlicePlan:
        user = (
            "Break this paper into verification slices for Aristotle. Order them so each slice depends only on earlier "
            "ones; a slice is a coherent unit Aristotle can complete in one session (one to a few lemmas). Include the "
            "main theorems as final slices. State the main claims precisely; they are the yardstick for the whole run.\n\n"
            f"<paper>\n{paper}\n</paper>\n"
        )
        if lean_report:
            user += f"\nThe Lean project already contains:\n<lean>\n{lean_report}\n</lean>\nReuse existing declarations where they fit.\n"
        return self._call(self.mathematician, user, SlicePlan, "plan")

    def instructions(self, plan, slice_, detail_level, history, handoff_notes) -> Instructions:
        user = (
            f"Write the instruction text for Aristotle for this slice at detail level {detail_level}.\n\n"
            f"<paper_summary>\n{plan.paper_summary}\n</paper_summary>\n"
            f"<slice>\n{slice_.model_dump_json(indent=2)}\n</slice>\n"
        )
        if history:
            user += f"<previous_attempts>\n{history}\n</previous_attempts>\n"
        if handoff_notes:
            user += f"<detailed_guidance>\n{handoff_notes}\n</detailed_guidance>\n"
        user += (
            "The instructions must tell Aristotle which declarations to create or fill, what each must state, and "
            "the proof approach appropriate to this detail level. Remind it to write SUMMARY.md and AXIOMS.txt."
        )
        return self._call(self.mathematician, user, Instructions, f"instructions-{slice_.id}")

    def grade(self, plan, slice_, attempt_prompt, task_status, task_summary, lean_report, attempt_no, max_attempts) -> Grade:
        user = (
            f"Aristotle finished attempt {attempt_no} of at most {max_attempts} on this slice with task status "
            f"{task_status}. Judge the result.\n\n"
            f"<main_claims>\n" + "\n".join(f"- {c}" for c in plan.main_claims) + "\n</main_claims>\n"
            f"<slice>\n{slice_.model_dump_json(indent=2)}\n</slice>\n"
            f"<instructions_sent>\n{attempt_prompt}\n</instructions_sent>\n"
            f"<aristotle_summary>\n{task_summary or '(none)'}\n</aristotle_summary>\n"
            f"<lean_check>\n{lean_report}\n</lean_check>\n\n"
            "Decide: accept (clean, and the statements match the goal), retry (same idea, more detail), handoff (Aristotle "
            "is stuck; you write the detailed mathematical route in handoff_notes), or give_up (this needs a human). "
            "Compare every relevant theorem statement to the slice goal and the paper's claims before deciding."
        )
        grade = self._call(self.mathematician, user, Grade, f"grade-{slice_.id}-{attempt_no}")
        if self.settings.use_referee:
            verdict = self._call(
                self.referee,
                user + f"\n\nThe mathematician's proposed judgment:\n<judgment>\n{grade.model_dump_json(indent=2)}\n</judgment>\n"
                "Do you agree? If not, give the corrected decision and fidelity.",
                RefereeVerdict,
                f"referee-{slice_.id}-{attempt_no}",
            )
            if not verdict.agrees:
                grade.reasoning += f"\n\nREFEREE OBJECTION: {verdict.objection}"
                if verdict.corrected_decision:
                    grade.decision = verdict.corrected_decision
                if verdict.corrected_fidelity:
                    grade.statement_fidelity = verdict.corrected_fidelity
        return grade

    def answer(self, plan, slice_, question, suggestions, recent_events) -> Answer:
        user = (
            "Aristotle paused mid-task and asked a question. Answer it so it can continue; if it is really asking for a "
            "route through a hard step, give the mathematical route.\n\n"
            f"<paper_summary>\n{plan.paper_summary}\n</paper_summary>\n"
            f"<slice>\n{slice_.model_dump_json(indent=2)}\n</slice>\n"
            f"<question>\n{question}\n</question>\n"
            + (f"<suggested_answers>\n" + "\n".join(f"- {s}" for s in suggestions) + "\n</suggested_answers>\n" if suggestions else "")
            + f"<recent_events>\n{recent_events}\n</recent_events>\n"
        )
        return self._call(self.mathematician, user, Answer, f"answer-{slice_.id}")

    def final_report(self, plan, lean_report) -> FinalReport:
        user = (
            "Every slice has been accepted. Do the final fidelity check: for each main claim of the paper, find the Lean "
            "theorem that establishes it and state whether the formal statement matches the claim exactly. Any "
            "discrepancy, sorry, or axiom means verified=false.\n\n"
            f"<main_claims>\n" + "\n".join(f"- {c}" for c in plan.main_claims) + "\n</main_claims>\n"
            f"<paper_summary>\n{plan.paper_summary}\n</paper_summary>\n"
            f"<lean_check>\n{lean_report}\n</lean_check>\n"
        )
        report = self._call(self.mathematician, user, FinalReport, "final")
        if self.settings.use_referee:
            verdict = self._call(
                self.referee,
                user + f"\n\nThe mathematician's report:\n<report>\n{report.model_dump_json(indent=2)}\n</report>\nDo you agree that verified={report.verified}?",
                RefereeVerdict,
                "referee-final",
            )
            if not verdict.agrees:
                report.caveats.append(f"REFEREE OBJECTION: {verdict.objection}")
                report.verified = False
        return report


class AdvisorError(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass
