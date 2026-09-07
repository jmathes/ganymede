from ganymede.lean_check import inspect_tarball, report_for_prompt, strip_comments


def test_strip_comments_preserves_lines():
    src = "a -- x\n/- b\n c -/ d\n"
    out = strip_comments(src)
    assert out.count("\n") == src.count("\n")
    assert "x" not in out and "b" not in out and "d" in out


def test_good_tarball_is_clean(good_tarball):
    r = inspect_tarball(good_tarball)
    assert r.clean
    assert r.sorries == [] and r.axioms == []
    names = {d.name for d in r.theorems}
    assert names == {"main_claim", "helper"}
    main = next(d for d in r.theorems if d.name == "main_claim")
    assert main.statement.startswith("theorem main_claim (n : ℕ) (h : 0 < n) : n ^ 2 ≥ n")
    assert "propext" in r.axiom_dump
    assert "proj/SUMMARY.md" in r.summary_files
    assert "no sorries" in r.brief()


def test_sorry_and_axiom_detected(sorry_tarball):
    r = inspect_tarball(sorry_tarball)
    assert not r.clean
    assert r.sorries == ["proj/Main.lean:3"]
    assert [a.name for a in r.axioms] == ["cheat"]
    text = report_for_prompt(r)
    assert "Remaining sorries" in text and "Declared axioms" in text
