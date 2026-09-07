# Reference

Background on the technologies Ganymede talks to. Verified September 2026 against the sources linked at the bottom; the Aristotle SDK details come from reading `aristotlelib` 2.1.0 directly.

## Aristotle

Aristotle is an AI agent made by Harmonic (a Palo Alto lab co-founded by Vlad Tenev and Tudor Achim) that produces machine-checked proofs in Lean 4. Harmonic's pitch is that unlike a chat model, Aristotle never returns a plausible-looking answer that might be wrong: every output is a Lean proof that the Lean compiler has accepted, and if it can't find one it says so. It got gold-medal-equivalent results on the 2025 IMO, was the first AI to autonomously resolve an Erdős problem (#728, January 2026), and has had code accepted into Mathlib unmodified.

Architecturally it is three things: a Lean proof-search engine, an informal reasoning module that proposes and formalizes helper lemmas in natural language, and a dedicated geometry solver. That informal module is why it can take English instructions and why it can "reflect on its own process" well enough to ask for help.

### What you give it and what you get back

There are two entry points.

- **Formalize a document.** Give it a paper (`.tex`, etc.) and it produces a Lean project from scratch: theorem statements plus proofs.
- **Work inside a Lean project.** Give it a directory containing a Lean project and a natural-language instruction. The canonical instruction is "fill in all sorries" (a `sorry` is Lean's placeholder for "proof omitted"), but it can also be told to add lemmas, restructure, simplify, or follow detailed step-by-step guidance. It edits files in place.

Either way the unit of work is a **project**, and the result comes back as a tarball of the whole project. Jobs run asynchronously on Harmonic's servers and take minutes to hours; an eight-hour run on a single olympiad problem is documented in the literature.

### Projects, tasks, and events

The API (v3, at `aristotle.harmonic.fun/api/v3`) has three objects, all exposed by the Python SDK.

- **Project.** Long-lived. Created with a prompt and an optional tarball. Status is `RUNNING` or `IDLE`. Files can be downloaded at any time: the result if there is one, otherwise the original input.
- **Task.** One unit of agent work within a project. Status is `QUEUED`, `IN_PROGRESS`, `COMPLETE`, `COMPLETE_WITH_ERRORS` (made progress, didn't finish), `OUT_OF_BUDGET` (ran out of time, resumable), `FAILED`, or `CANCELED`. Has a `percent_complete` and an `output_summary`.
- **Event.** A streamed log entry within a task, delivered over server-sent events. Types include `THINKING`, `PROVING`, `EDITING_FILE`, `RUNNING_LEAN`, `BUILDING`, `REVIEWING`, `SEARCHING_EXTERNAL`, `SUMMARY`, `FINISHED`, `ERROR`, and two that matter most for Ganymede: `QUESTION` and `AGENT_QUESTION`.

### Features that matter for Ganymede

**Follow-up prompts on an existing project.** `Project.ask(prompt, mode, files)` sends a new prompt into a project. `INSTRUCT` mode changes direction if a task is running or starts a new task if idle, and can carry uploaded files. `ASK` mode asks a question about the most recent task without starting work. This is the "carry the next slice's instructions back to Aristotle" step, and it means one paper can be one Aristotle project across many slices, with Aristotle keeping its context.

**Aristotle can ask questions and a program can answer them.** If a project is created with `agent_questions_setting=TIMEOUT_15_MIN`, Aristotle may emit an `AGENT_QUESTION` event mid-task, optionally with suggested answers. The SDK's `Event.answer(text)` posts a reply. If nobody answers within 15 minutes, Aristotle goes with its best guess and continues. The CLI's `--wait` mode handles this by prompting a human at the terminal. This is the formal version of the "Claude handoff": Ganymede can catch these events, route the question to the mathematician model, and answer within the window.

**Cancel and resume.** Tasks can be canceled; an `OUT_OF_BUDGET` task resumes by sending a "continue" instruction. Together with `INSTRUCT`-while-running, this is what lets an orchestrator stop Aristotle, get better instructions, and restart it.

**Upload rules.** The SDK tars the project directory itself. It honors `.gitignore` but force-includes `.lake/`, skips compiled `.olean` artifacts and build outputs, skips the standard Mathlib dependency set (Aristotle already has mathlib, batteries, aesop, Qq, etc.), and rejects any single file over 100 MiB. It refuses projects whose `lake-manifest.json` references local-path dependencies, since Aristotle can't fetch those.

### Access

Sign up at aristotle.harmonic.fun, create an API key under Dashboard → API Keys, and set `ARISTOTLE_API_KEY`. As of this writing access is free with no paid tier. The SDK needs Python 3.10+ and depends only on `httpx`, `pathspec`, and `pydantic`.

```bash
pip install aristotlelib
aristotle submit "Fill in all sorries" --project-dir ./proj --wait --destination out.tar.gz
aristotle continue <project-id> "Now prove lemma 3 using the approach below: ..." --mode instruct --files notes.md --wait
aristotle continue <project-id> "Which lemma are you stuck on?" --mode ask
aristotle show <project-id>            # task status and recent events
aristotle download <project-id> --destination out.tar.gz
aristotle cancel <project-id>
```

Python, roughly the same surface:

```python
from aristotlelib import Project, FollowUpMode, AgentQuestionsSetting

p = await Project.create_from_directory("Fill in all sorries", "./proj",
        agent_questions_setting=AgentQuestionsSetting.TIMEOUT_15_MIN)
tasks, _ = await p.get_tasks(limit=1)
await tasks[0].wait_for_completion()     # or stream events yourself and answer AGENT_QUESTIONs
await p.get_files("out.tar.gz")
await p.ask("Next slice: ...", mode=FollowUpMode.INSTRUCT, files=["slice2.md"])
```

### What it does not do

- It does not guarantee that the Lean statement matches the paper's claim. Both the formalize path and the sorry-filling path can quietly generalize, specialize, or reinterpret a theorem. The published case studies check this by hand. The Grasshopper case study's advice is that a result "should be inspected at the level of declarations, dependencies, placeholders, and proof obligations": a green build with a `sorry` still in it, or with the main theorem weakened, is not a proof of the paper.
- It has no documented concurrency or rate limits, no documented project-size limit beyond the per-file cap, and no SLA. Assume long jobs and occasional `FAILED` with "the team at Harmonic has been notified."
- The one published multi-lemma case study found Aristotle good at bounded local lemmas and weak at the global bookkeeping that ties them together. That is the bottleneck where the "Claude handoff" is expected to help.

### Observed behavior (one real job, 2026-09-07)

From submitting `examples/toy/` (two `sorry`s, no Mathlib) through `ganymede/formalizer.py` with questions enabled; full log in `examples/toy/aristotle_run.log`.

- Total wall time was under three minutes. Aristotle asked its question at the start, got the answer from code within a second, acknowledged it in the event stream, and continued.
- `AGENT_QUESTION` events arrive with `suggestions` (three suggested answers in this case). The same question is re-emitted after answering, with the answer attached; treat repeats by event id.
- The task ended with status `COMPLETE_WITH_ERRORS` even though the result was clean, the summary said so, and it rebuilt locally. Do not use task status as a success signal; use the tarball.
- The result tarball was 1.5 KB: `.lake/` is not included. Files sit under a top-level directory named `<project>_aristotle/`. Aristotle adds `ARISTOTLE_SUMMARY.md` and a `README.md` on its own, and wrote the `SUMMARY.md` and `AXIOMS.txt` it was asked for.
- Events include the exact shell commands Aristotle ran (`sed -i ...`, `lake build`) and file edits, so the stream is enough to reconstruct what it did. It committed and pushed to its own git remote at the end.
- Without Mathlib it had to prove `sumOdd n = n * n` with `Nat.succ_mul`, `Nat.mul_succ`, and `omega`, and did so on the second try.

## Sources

- [Aristotle](https://aristotle.harmonic.fun/) (Harmonic)
- [aristotlelib on PyPI](https://pypi.org/project/aristotlelib/), plus the 2.1.0 source
- [Aristotle: IMO-level Automated Theorem Proving](https://arxiv.org/abs/2510.01346) (Harmonic, 2025)
- [Using the Aristotle API for AI-Assisted Theorem Proving in Lean 4: the Grasshopper Problem](https://arxiv.org/html/2605.20120v1) (2026)
- [Resolution of Erdős Problem #728: a writeup of Aristotle's Lean proof](https://arxiv.org/html/2601.07421v1) (2026)
- [septract/lean-aristotle-mcp](https://github.com/septract/lean-aristotle-mcp), an existing MCP wrapper
- [What Is the Harmonic Aristotle API?](https://eco.com/support/en/articles/14114345-what-is-the-harmonic-aristotle-api-formal-verification-ai-for-developers)
