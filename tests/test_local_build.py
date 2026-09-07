import shutil
from pathlib import Path

import pytest

from ganymede.lean_check import local_build, local_build_for_prompt

TOY_RESULT = Path(__file__).parent.parent / "examples" / "toy" / "aristotle_result.tar.gz"
HAS_LAKE = shutil.which("lake") or (Path.home() / ".elan" / "bin" / "lake").exists()


@pytest.mark.skipif(not HAS_LAKE, reason="lake not installed")
def test_local_build_of_real_aristotle_result():
    lb = local_build(TOY_RESULT, timeout_s=600)
    assert lb.ran and lb.ok, lb.output
    assert set(lb.axioms) == {"two_mul_eq_add", "sumOdd_eq_sq"}
    assert lb.unexpected_axioms == []
    assert "OK" in local_build_for_prompt(lb)


def test_local_build_without_lake(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    lb = local_build(TOY_RESULT)
    assert not lb.ran and "not run" in local_build_for_prompt(lb)


def test_ensure_built_runs_cache_then_build_for_mathlib(tmp_path, monkeypatch):
    import subprocess

    from ganymede.lean_check import ensure_built

    (tmp_path / "lakefile.toml").write_text('[[require]]\nname = "mathlib"\n')
    calls = []

    def runner(argv, **kw):
        calls.append(argv[1:])
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr("shutil.which", lambda _: "/fake/lake")
    monkeypatch.setattr(Path, "exists", lambda self: True)
    assert ensure_built(tmp_path, runner=runner)
    assert calls == [["exe", "cache", "get"], ["build"]]


def test_ensure_built_plain_project_only_builds(tmp_path, monkeypatch):
    import subprocess

    from ganymede.lean_check import ensure_built

    (tmp_path / "lakefile.toml").write_text('name = "toy"\n')
    calls = []
    monkeypatch.setattr("shutil.which", lambda _: "/fake/lake")
    monkeypatch.setattr(Path, "exists", lambda self: True)
    assert not ensure_built(tmp_path, runner=lambda argv, **kw: (calls.append(argv[1:]), subprocess.CompletedProcess(argv, 1, "", "boom"))[1])
    assert calls == [["build"]]
