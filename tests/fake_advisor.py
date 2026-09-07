"""Scripted mathematician/referee for orchestrator tests."""

from ganymede.advisor import Answer, FinalReport, Grade, Instructions, SlicePlan, SliceSpec
from ganymede.state import Spend


class FakeAdvisor:
    def __init__(self, grades: list[Grade], final_verified: bool = True, slices: list[SliceSpec] | None = None):
        self.spend = Spend()
        self.grades = list(grades)
        self.final_verified = final_verified
        self.slices = slices or [SliceSpec(id="s1", title="main", goal="n^2 >= n for n > 0", lean_targets=["main_claim"])]
        self.questions: list[str] = []
        self.instruction_levels: list[int] = []

    def _tick(self):
        self.spend.claude_calls += 1

    def plan(self, paper, lean_report):
        self._tick()
        return SlicePlan(paper_summary="one theorem", main_claims=["n^2 >= n for n > 0"], slices=self.slices)

    def instructions(self, plan, slice_, detail_level, history, handoff_notes):
        self._tick()
        self.instruction_levels.append(detail_level)
        return Instructions(detail_level=detail_level, prompt=f"prove {slice_.id} at level {detail_level}; notes={handoff_notes or ''}")

    def grade(self, plan, slice_, attempt_prompt, task_status, task_summary, lean_report, attempt_no, max_attempts):
        self._tick()
        return self.grades.pop(0)

    def answer(self, plan, slice_, question, suggestions, recent_events):
        self._tick()
        self.questions.append(question)
        return Answer(answer="use induction", reasoning="obvious")

    def final_report(self, plan, lean_report):
        self._tick()
        return FinalReport(verified=self.final_verified, claim_status=["main_claim matches"], caveats=[], summary="ok")


def accept(fidelity="matches"):
    return Grade(decision="accept", statement_fidelity=fidelity, fidelity_notes="", reasoning="clean", next_detail_level=0)


def retry(level=1):
    return Grade(decision="retry", statement_fidelity="unclear", fidelity_notes="", reasoning="sorry left", next_detail_level=level)


def handoff(notes="do the bound first"):
    return Grade(decision="handoff", statement_fidelity="unclear", fidelity_notes="", reasoning="stuck", next_detail_level=2, handoff_notes=notes)


def give_up():
    return Grade(decision="give_up", statement_fidelity="differs", fidelity_notes="", reasoning="needs human", next_detail_level=3)
