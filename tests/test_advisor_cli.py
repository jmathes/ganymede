import json
import subprocess

import pytest

from ganymede.advisor import AdvisorError, Answer, ClaudeCodeAdvisor, SlicePlan, SliceSpec
from ganymede.config import Settings


def fake_runner(stdout: str, code: int = 0):
    calls = []

    def run(argv, stdin):
        calls.append((argv, stdin))
        return subprocess.CompletedProcess(argv, code, stdout=stdout, stderr="")

    run.calls = calls
    return run


def plan():
    return SlicePlan(paper_summary="s", main_claims=["c"], slices=[SliceSpec(id="s1", title="t", goal="g")])


def test_cli_backend_parses_structured_output(tmp_path):
    payload = {"structured_output": {"answer": "use induction", "reasoning": "r"}, "is_error": False,
               "usage": {"input_tokens": 10, "cache_read_input_tokens": 5, "output_tokens": 7}}
    runner = fake_runner(json.dumps(payload))
    adv = ClaudeCodeAdvisor(Settings(model="m", effort="low", use_referee=False), transcript_dir=tmp_path, runner=runner)
    out = adv.answer(plan(), plan().slices[0], "q?", [], "")
    assert isinstance(out, Answer) and out.answer == "use induction"
    assert adv.spend.claude_calls == 1 and adv.spend.claude_input_tokens == 15 and adv.spend.claude_output_tokens == 7
    argv, stdin = runner.calls[0]
    assert argv[:2] == ["claude", "-p"] and "--json-schema" in argv and "--tools" in argv
    assert argv[argv.index("--model") + 1] == "m" and argv[argv.index("--effort") + 1] == "low"
    assert "q?" in stdin
    assert "mathematician" in argv[argv.index("--system-prompt") + 1].lower()
    assert list(tmp_path.glob("0001-answer-s1.md"))


def test_cli_backend_error_paths(tmp_path):
    adv = ClaudeCodeAdvisor(Settings(use_referee=False), runner=fake_runner("not json"))
    with pytest.raises(AdvisorError, match="non-JSON"):
        adv.answer(plan(), plan().slices[0], "q", [], "")
    adv = ClaudeCodeAdvisor(Settings(use_referee=False), runner=fake_runner(json.dumps({"is_error": True, "result": "boom"})))
    with pytest.raises(AdvisorError, match="boom"):
        adv.answer(plan(), plan().slices[0], "q", [], "")
    adv = ClaudeCodeAdvisor(Settings(use_referee=False), runner=fake_runner("", code=1))
    with pytest.raises(AdvisorError, match="exit 1"):
        adv.answer(plan(), plan().slices[0], "q", [], "")


def test_make_advisor_picks_cli_without_api_key(monkeypatch):
    from ganymede.advisor import ClaudeAdvisor, make_advisor

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert isinstance(make_advisor(Settings(claude_backend="auto")), ClaudeCodeAdvisor)
    assert isinstance(make_advisor(Settings(claude_backend="cli")), ClaudeCodeAdvisor)
