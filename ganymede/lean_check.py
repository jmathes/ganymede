"""Definition of done for a Lean result (TODO step 3), applied to an Aristotle result tarball.

This is static: it reads the .lean sources and reports what a human would look for before trusting a
green build. Ganymede never runs `lake` itself. The three checks that matter:

  1. No `sorry` anywhere outside comments.
  2. No user-declared `axiom` (Aristotle proving a theorem by assuming it).
  3. The main theorem statements, extracted verbatim, so the mathematician can compare them to
     the paper's claims. A compiling proof of the wrong statement is the failure mode we fear most.

If Aristotle was asked to write `#print axioms` output to a file (we ask it to, see prompts), the
report includes that too.
"""

from __future__ import annotations

import re
import tarfile
from pathlib import Path, PurePosixPath

from pydantic import BaseModel

DECL_RE = re.compile(
    r"^\s*(?:@\[[^\]]*\]\s*)*(?:private\s+|protected\s+|noncomputable\s+|unsafe\s+|partial\s+)*"
    r"(theorem|lemma|axiom|def|instance|abbrev|structure|inductive|opaque)\s+([^\s:({\[]+)",
    re.MULTILINE,
)
SORRY_RE = re.compile(r"\bsorry\b")
SUSPICIOUS_RE = re.compile(r"\b(native_decide|unsafe|implemented_by|extern)\b")


class Declaration(BaseModel):
    file: str
    kind: str
    name: str
    line: int
    statement: str  # text from the declaration keyword up to `:=` or `where` or `|`, single-spaced


class LeanReport(BaseModel):
    source: str
    lean_files: list[str] = []
    sorries: list[str] = []            # "file:line"
    axioms: list[Declaration] = []
    suspicious: list[str] = []         # "file:line: token"
    theorems: list[Declaration] = []
    axiom_dump: str | None = None      # contents of an AXIOMS file if Aristotle wrote one
    summary_files: dict[str, str] = {} # any *.md at top level (Aristotle writes summaries)

    @property
    def clean(self) -> bool:
        return not self.sorries and not self.axioms

    def brief(self) -> str:
        parts = [f"{len(self.lean_files)} lean files, {len(self.theorems)} theorems/lemmas"]
        parts.append(f"{len(self.sorries)} sorries" if self.sorries else "no sorries")
        parts.append(f"{len(self.axioms)} axioms" if self.axioms else "no axioms")
        if self.suspicious:
            parts.append(f"{len(self.suspicious)} suspicious tokens")
        return ", ".join(parts)


def strip_comments(src: str) -> str:
    """Replace comment text with spaces, preserving newlines so line numbers survive."""
    out: list[str] = []
    i, n = 0, len(src)
    depth = 0
    while i < n:
        two = src[i : i + 2]
        if depth == 0 and two == "--":
            j = src.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i))
            i = j
        elif two == "/-":
            depth += 1
            out.append("  ")
            i += 2
        elif depth > 0 and two == "-/":
            depth -= 1
            out.append("  ")
            i += 2
        elif depth > 0:
            out.append("\n" if src[i] == "\n" else " ")
            i += 1
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


def _statement_text(code: str, start: int, after: int) -> str:
    """From the declaration keyword, take text up to the first `:=`, `where`, `|`, or next declaration."""
    end = len(code)
    for pat in (":=", "\nwhere", "\n  |", "\n|"):
        k = code.find(pat, after)
        if k != -1:
            end = min(end, k)
    m = DECL_RE.search(code, after)
    if m:
        end = min(end, m.start(1))
    return " ".join(code[start:end].split())


def analyze_source(file: str, src: str) -> tuple[list[Declaration], list[int], list[tuple[int, str]]]:
    code = strip_comments(src)
    decls: list[Declaration] = []
    for m in DECL_RE.finditer(code):
        line = code.count("\n", 0, m.start(1)) + 1
        decls.append(
            Declaration(file=file, kind=m.group(1), name=m.group(2), line=line, statement=_statement_text(code, m.start(1), m.end()))
        )
    sorry_lines = [code.count("\n", 0, m.start()) + 1 for m in SORRY_RE.finditer(code)]
    suspicious = [(code.count("\n", 0, m.start()) + 1, m.group(1)) for m in SUSPICIOUS_RE.finditer(code)]
    return decls, sorry_lines, suspicious


def _is_project_source(name: str) -> bool:
    p = PurePosixPath(name)
    return p.suffix == ".lean" and ".lake" not in p.parts and "lakefile" not in p.name


def inspect_tarball(path: Path | str) -> LeanReport:
    path = Path(path)
    report = LeanReport(source=str(path))
    with tarfile.open(path, "r:*") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            name = member.name.lstrip("./")
            p = PurePosixPath(name)
            if _is_project_source(name):
                data = tar.extractfile(member).read().decode("utf-8", errors="replace")
                _ingest(report, name, data)
            elif p.name.upper().startswith("AXIOMS") and ".lake" not in p.parts:
                report.axiom_dump = tar.extractfile(member).read().decode("utf-8", errors="replace")
            elif p.suffix == ".md" and len(p.parts) <= 2 and ".lake" not in p.parts:
                report.summary_files[name] = tar.extractfile(member).read().decode("utf-8", errors="replace")[:20000]
    return report


def inspect_directory(root: Path | str) -> LeanReport:
    root = Path(root)
    report = LeanReport(source=str(root))
    for f in sorted(root.rglob("*.lean")):
        rel = f.relative_to(root).as_posix()
        if _is_project_source(rel):
            _ingest(report, rel, f.read_text(encoding="utf-8", errors="replace"))
    for f in root.glob("AXIOMS*"):
        report.axiom_dump = f.read_text(errors="replace")
    return report


def _ingest(report: LeanReport, name: str, src: str) -> None:
    report.lean_files.append(name)
    decls, sorry_lines, suspicious = analyze_source(name, src)
    report.sorries += [f"{name}:{ln}" for ln in sorry_lines]
    report.suspicious += [f"{name}:{ln}: {tok}" for ln, tok in suspicious]
    for d in decls:
        if d.kind == "axiom":
            report.axioms.append(d)
        elif d.kind in ("theorem", "lemma"):
            report.theorems.append(d)


def report_for_prompt(report: LeanReport, max_theorems: int = 200) -> str:
    """Render a report the way the mathematician model should see it."""
    lines = [f"Lean check of {report.source}: {report.brief()}"]
    if report.sorries:
        lines.append("Remaining sorries:")
        lines += [f"  {s}" for s in report.sorries]
    if report.axioms:
        lines.append("Declared axioms (a proof that depends on these is NOT a proof):")
        lines += [f"  {a.file}:{a.line}: {a.statement}" for a in report.axioms]
    if report.suspicious:
        lines.append("Suspicious tokens:")
        lines += [f"  {s}" for s in report.suspicious]
    if report.axiom_dump:
        lines.append("#print axioms output:")
        lines.append(report.axiom_dump.strip())
    lines.append("Theorem and lemma statements:")
    for d in report.theorems[:max_theorems]:
        lines.append(f"  {d.file}:{d.line}: {d.statement}")
    if len(report.theorems) > max_theorems:
        lines.append(f"  ... {len(report.theorems) - max_theorems} more")
    for name, text in report.summary_files.items():
        lines.append(f"--- {name} ---")
        lines.append(text.strip())
    return "\n".join(lines)

