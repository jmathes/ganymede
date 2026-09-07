from pathlib import Path

import pytest

from ganymede.advisor import SliceSpec
from ganymede.config import Settings
from ganymede.formalizer import FakeFormalizer
from ganymede.orchestrator import Orchestrator
from ganymede.state import Run
from tests.fake_advisor import FakeAdvisor, accept, give_up, handoff, retry


def settings(tmp_path, **kw) -> Settings:
    s = Settings(runs_dir=tmp_path / "runs", use_referee=False, max_attempts_per_slice=3, max_aristotle_tasks=10, max_claude_calls=50, local_build=False)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def new_run(paper, s: Settings) -> Run:
    run = Run(run_id="t1", paper_path=str(paper))
    run.save(s.runs_dir)
    return run


async def test_happy_path_one_slice(tmp_path, paper, good_tarball):
    s = settings(tmp_path)
    adv = FakeAdvisor(grades=[accept()])
    form = FakeFormalizer(script=[("COMPLETE", good_tarball, None)])
    run = await Orchestrator(new_run(paper, s), s, adv, form).run_to_completion()
    assert run.status == "done"
    assert run.aristotle_project_id == "fake-project"
    assert run.slices[0].status == "accepted"
    assert (s.runs_dir / "t1" / "REPORT.md").exists()
    assert (s.runs_dir / "t1" / "plan.json").exists()
    assert run.spend.aristotle_tasks == 1
    # state on disk matches
    assert Run.load(s.runs_dir, "t1").status == "done"


async def test_retry_then_handoff_raises_detail_level(tmp_path, paper, good_tarball, sorry_tarball):
    s = settings(tmp_path)
    adv = FakeAdvisor(grades=[retry(level=1), handoff("spell out the bound"), accept()])
    form = FakeFormalizer(script=[
        ("COMPLETE_WITH_ERRORS", sorry_tarball, None),
        ("OUT_OF_BUDGET", sorry_tarball, None),
        ("COMPLETE", good_tarball, None),
    ])
    run = await Orchestrator(new_run(paper, s), s, adv, form).run_to_completion()
    assert run.status == "done"
    assert adv.instruction_levels == [0, 1, 2]
    assert "spell out the bound" in form.prompts[2]
    assert len(run.slices[0].attempts) == 3
    assert [a.decision for a in run.slices[0].attempts] == ["retry", "handoff", "accept"]


async def test_aristotle_question_is_answered(tmp_path, paper, good_tarball):
    s = settings(tmp_path)
    adv = FakeAdvisor(grades=[accept()])
    form = FakeFormalizer(script=[("COMPLETE", good_tarball, "Should I use induction?")])
    run = await Orchestrator(new_run(paper, s), s, adv, form).run_to_completion()
    assert run.status == "done"
    assert adv.questions == ["Should I use induction?"]
    assert form.answers == ["use induction"]


async def test_static_check_overrides_bad_accept(tmp_path, paper, good_tarball, sorry_tarball):
    """The mathematician says accept, but the tarball still has a sorry. Static check wins."""
    s = settings(tmp_path)
    adv = FakeAdvisor(grades=[accept(), accept()])
    form = FakeFormalizer(script=[("COMPLETE", sorry_tarball, None), ("COMPLETE", good_tarball, None)])
    run = await Orchestrator(new_run(paper, s), s, adv, form).run_to_completion()
    assert run.status == "done"
    assert run.slices[0].attempts[0].decision == "retry"
    assert "static check" in run.slices[0].handoff_notes


async def test_give_up_halts_with_blocked_slice(tmp_path, paper, sorry_tarball):
    s = settings(tmp_path)
    adv = FakeAdvisor(grades=[give_up()])
    form = FakeFormalizer(script=[("COMPLETE_WITH_ERRORS", sorry_tarball, None)])
    run = await Orchestrator(new_run(paper, s), s, adv, form).run_to_completion()
    assert run.status == "halted"
    assert "blocked slices: ['s1']" in run.halt_reason


async def test_max_attempts_guard(tmp_path, paper, sorry_tarball):
    s = settings(tmp_path, max_attempts_per_slice=2)
    adv = FakeAdvisor(grades=[retry(), retry()])
    form = FakeFormalizer(script=[("COMPLETE_WITH_ERRORS", sorry_tarball, None)] * 2)
    run = await Orchestrator(new_run(paper, s), s, adv, form).run_to_completion()
    assert run.status == "halted"
    assert run.slices[0].status == "blocked"
    assert len(run.slices[0].attempts) == 2


async def test_aristotle_task_budget_guard(tmp_path, paper, sorry_tarball):
    s = settings(tmp_path, max_aristotle_tasks=1)
    adv = FakeAdvisor(grades=[retry(), retry()])
    form = FakeFormalizer(script=[("COMPLETE_WITH_ERRORS", sorry_tarball, None)] * 2)
    run = await Orchestrator(new_run(paper, s), s, adv, form).run_to_completion()
    assert run.status == "halted"
    assert "aristotle task budget" in run.halt_reason


async def test_failed_task_is_retried_without_grading(tmp_path, paper, good_tarball):
    s = settings(tmp_path)
    adv = FakeAdvisor(grades=[accept()])
    form = FakeFormalizer(script=[("FAILED", None, None), ("COMPLETE", good_tarball, None)])
    run = await Orchestrator(new_run(paper, s), s, adv, form).run_to_completion()
    assert run.status == "done"
    assert run.slices[0].attempts[0].task_status == "FAILED"
    assert run.slices[0].attempts[0].tarball is None


async def test_dependencies_and_resume(tmp_path, paper, good_tarball):
    s = settings(tmp_path)
    slices = [
        SliceSpec(id="a", title="A", goal="lemma"),
        SliceSpec(id="b", title="B", goal="main", depends_on=["a"]),
    ]
    adv = FakeAdvisor(grades=[accept()], slices=slices)
    # Only one scripted Aristotle step: the second call will crash.
    form = FakeFormalizer(script=[("COMPLETE", good_tarball, None)])
    run = await Orchestrator(new_run(paper, s), s, adv, form).run_to_completion()
    assert run.status == "failed"
    assert run.slices[0].status == "accepted" and run.slices[1].status == "running"
    assert run.slices[1].attempts[0].aristotle_task_id == "task-2"

    # Resume from disk: the in-flight task for slice b is picked up, not resubmitted.
    run2 = Run.load(s.runs_dir, "t1")
    adv2 = FakeAdvisor(grades=[accept()], slices=slices)
    form2 = FakeFormalizer(script=[("COMPLETE", good_tarball, None)])
    form2.project_id = None
    orch = Orchestrator(run2, s, adv2, form2)
    assert form2.project_id == "fake-project"
    run2 = await orch.run_to_completion()
    assert run2.status == "done"
    assert form2.prompts == []  # nothing resubmitted
    assert len(run2.slices[1].attempts) == 1


async def test_final_report_not_verified_halts(tmp_path, paper, good_tarball):
    s = settings(tmp_path)
    adv = FakeAdvisor(grades=[accept()], final_verified=False)
    form = FakeFormalizer(script=[("COMPLETE", good_tarball, None)])
    run = await Orchestrator(new_run(paper, s), s, adv, form).run_to_completion()
    assert run.status == "halted"
    assert "final check not verified" in run.halt_reason


async def test_template_project_used_when_none_given(tmp_path, paper, good_tarball):
    s = settings(tmp_path)
    adv = FakeAdvisor(grades=[accept()])
    form = FakeFormalizer(script=[("COMPLETE", good_tarball, None)])
    run = await Orchestrator(new_run(paper, s), s, adv, form).run_to_completion()
    assert run.status == "done"
    proj = Path(run.lean_project_dir)
    assert proj == s.runs_dir / "t1" / "project"
    assert (proj / "lakefile.toml").exists() and (proj / "lean-toolchain").read_text().strip() == "leanprover/lean4:v4.28.0"
    assert 'rev = "v4.28.0"' in (proj / "lakefile.toml").read_text()
