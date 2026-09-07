import io
import tarfile
from pathlib import Path

import pytest

GOOD_LEAN = """
import Mathlib
-- a comment with sorry in it
/- block comment
   sorry
-/
theorem main_claim (n : ℕ) (h : 0 < n) : n ^ 2 ≥ n := by
  nlinarith

lemma helper (a b : ℕ) : a + b = b + a := by
  omega
"""

SORRY_LEAN = """
theorem main_claim (n : ℕ) (h : 0 < n) : n ^ 2 ≥ n := by
  sorry
axiom cheat : ∀ n : ℕ, n = n
"""


def make_tarball(path: Path, files: dict[str, str]) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


@pytest.fixture
def good_tarball(tmp_path):
    return make_tarball(tmp_path / "good.tar.gz", {"proj/Main.lean": GOOD_LEAN, "proj/SUMMARY.md": "done", "proj/AXIOMS.txt": "'main_claim' depends on axioms: [propext, Classical.choice, Quot.sound]"})


@pytest.fixture
def sorry_tarball(tmp_path):
    return make_tarball(tmp_path / "sorry.tar.gz", {"proj/Main.lean": SORRY_LEAN})


@pytest.fixture
def paper(tmp_path):
    p = tmp_path / "paper.md"
    p.write_text("# A theorem\n\nTheorem 1. For n > 0, n^2 >= n.\n")
    return p
