"""Definition of done for a Lean result (TODO step 3), applied to an Aristotle result tarball.

The core check is static: it reads the .lean sources and reports what a human would look for before
trusting a green build. When a Lean toolchain is installed, `local_build` also rebuilds the result and
prints its axioms, and `ensure_built` prepares a project before upload. The three static checks:

  1. No `sorry` anywhere outside comments.
  2. No user-declared `axiom` (Aristotle proving a theorem by assuming it).
  3. The main theorem statements, extracted verbatim, so the mathematician can compare them to
     the paper's claims. A compiling proof of the wrong statement is the failure mode we fear most.

If Aristotle was asked to write `#print axioms` output to a file (we ask it to, see prompts), the
report includes that too.
"""

from __future__ import annotations

import os
import logging
import re

log = logging.getLogger("ganymede")
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


# ---- optional local verification (needs elan/lake on PATH) -----------------

class LocalBuild(BaseModel):
    ran: bool
    ok: bool = False
    axioms: dict[str, str] = {}      # theorem name -> "#print axioms" line
    unexpected_axioms: list[str] = []  # theorems depending on anything beyond the standard three
    output: str = ""

STANDARD_AXIOMS = {"propext", "Quot.sound", "Classical.choice"}
AXIOM_LINE_RE = re.compile(r"'([^']+)' (?:depends on axioms: \[([^\]]*)\]|does not depend on any axioms)")


def local_build(tarball: Path | str, timeout_s: float = 3600, workdir: Path | None = None) -> LocalBuild:
    """Extract a result tarball, run `lake build`, and `#print axioms` for every theorem it declares.

    Independent of Aristotle's own build: this is Lean on this machine checking the same files. If lake
    is not installed, returns ran=False. A Mathlib project needs its dependencies fetched, which lake
    does on first build (large download); the timeout covers that.
    """
    import shutil as _shutil
    import subprocess
    import tempfile

    lake = _shutil.which("lake") or (Path.home() / ".elan" / "bin" / "lake")
    if not Path(lake).exists():
        return LocalBuild(ran=False, output="lake not found; install elan (see REFERENCE.md)")

    tarball = Path(tarball)
    tmp = tempfile.mkdtemp(prefix="ganymede-verify-", dir=workdir)
    try:
        with tarfile.open(tarball, "r:*") as tar:
            tar.extractall(tmp, filter="data")
        roots = [p for p in Path(tmp).iterdir() if p.is_dir()]
        root = roots[0] if len(roots) == 1 and not (Path(tmp) / "lakefile.toml").exists() and not (Path(tmp) / "lakefile.lean").exists() else Path(tmp)
        env = {**os.environ, "PATH": f"{Path(lake).parent}:{os.environ.get('PATH', '')}"}
        build = subprocess.run([str(lake), "build"], cwd=root, capture_output=True, text=True, timeout=timeout_s, env=env)
        out = build.stdout[-4000:] + build.stderr[-4000:]
        if build.returncode != 0:
            return LocalBuild(ran=True, ok=False, output=out)
        # Import every project module and print axioms for every theorem/lemma we found statically.
        report = inspect_directory(root)
        modules = sorted({f[:-5].replace("/", ".") for f in report.lean_files})
        names = [d.name for d in report.theorems]
        probe = root / "GanymedeAxioms.lean"
        probe.write_text("".join(f"import {m}\n" for m in modules) + "".join(f"#print axioms {n}\n" for n in names))
        pa = subprocess.run([str(lake), "env", "lean", str(probe)], cwd=root, capture_output=True, text=True, timeout=timeout_s, env=env)
        axioms: dict[str, str] = {}
        unexpected: list[str] = []
        for m in AXIOM_LINE_RE.finditer(pa.stdout):
            axioms[m.group(1)] = m.group(0)
            used = {a.strip() for a in (m.group(2) or "").split(",") if a.strip()}
            if used - STANDARD_AXIOMS:
                unexpected.append(m.group(1))
        return LocalBuild(ran=True, ok=pa.returncode == 0 and "sorryAx" not in pa.stdout, axioms=axioms, unexpected_axioms=unexpected, output=out + pa.stdout[-4000:] + pa.stderr[-2000:])
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)


def local_build_for_prompt(lb: LocalBuild) -> str:
    if not lb.ran:
        return f"Local Lean build: not run ({lb.output})"
    lines = [f"Local Lean build on this machine: {'OK' if lb.ok else 'FAILED'}"]
    for name, line in lb.axioms.items():
        lines.append("  " + line)
    if lb.unexpected_axioms:
        lines.append("  UNEXPECTED AXIOMS in: " + ", ".join(lb.unexpected_axioms))
    if not lb.ok:
        lines.append(lb.output.strip()[-3000:])
    return "\n".join(lines)


def ensure_built(project_dir: Path | str, timeout_s: float = 3600, runner=None) -> bool:
    """Run `lake build` in a Lean project before uploading it, so Aristotle gets a `.lake` folder and
    the SDK stops warning. For a Mathlib project, fetch the prebuilt cache first (`lake exe cache get`)
    so the build takes minutes rather than hours. Returns True if the build succeeded. A missing lake
    or a failed build is logged and returns False; the upload proceeds either way."""
    import shutil as _shutil
    import subprocess

    runner = runner or subprocess.run
    project_dir = Path(project_dir)
    lake = _shutil.which("lake") or (Path.home() / ".elan" / "bin" / "lake")
    if not Path(lake).exists():
        log.warning("lake not found; uploading %s without a .lake folder", project_dir)
        return False
    env = {**os.environ, "PATH": f"{Path(lake).parent}:{os.environ.get('PATH', '')}"}
    lakefiles = [project_dir / "lakefile.toml", project_dir / "lakefile.lean"]
    uses_mathlib = any(f.is_file() and "mathlib" in f.read_text().lower() for f in lakefiles)
    steps = ([["exe", "cache", "get"]] if uses_mathlib else []) + [["build"]]
    for step in steps:
        log.info("lake %s in %s", " ".join(step), project_dir)
        try:
            proc = runner([str(lake), *step], cwd=project_dir, capture_output=True, text=True, timeout=timeout_s, env=env)
        except subprocess.TimeoutExpired:
            log.warning("lake %s timed out after %.0fs", " ".join(step), timeout_s)
            return False
        if proc.returncode != 0:
            log.warning("lake %s failed:\n%s", " ".join(step), (proc.stdout + proc.stderr)[-3000:])
            if step == ["build"]:
                return False
    return True
