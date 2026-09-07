Status as of 2026-09-07. Steps marked DONE are implemented and unit-tested with fakes; nothing has yet run against the live Aristotle or Claude APIs.

1. BLOCKED (needs `ARISTOTLE_API_KEY`): Get an Aristotle API key and run one job by hand: submit a Lean project with sorries, watch the event stream, download the tarball, inspect it. Confirm agent questions actually fire with `TIMEOUT_15_MIN` and can be answered from code. Then run `ganymede run` on a toy paper and fix whatever the SDK does differently from what `ganymede/formalizer.py` assumes.
2. BLOCKED (needs the professor): Collect the professor's current artifacts: one real slicing prompt, one Claude grading of an Aristotle result, one "Claude handoff" exchange. Fold them into `ganymede/prompts/*.md`, which are currently written from the README conversation alone.
3. DONE: Define "done" for a slice and for a paper. `ganymede/lean_check.py`: no `sorry`, no user `axiom`, suspicious tokens flagged, theorem statements extracted for comparison; the mathematician and referee must also judge statement fidelity "matches". Not done: running `#print axioms` locally, since there is no Lean toolchain here; Aristotle is asked to write `AXIOMS.txt` instead.
4. DONE: Build the smallest loop with no slicing. `ganymede/orchestrator.py` with the single-slice happy path tested.
5. DONE: Make it resumable. `ganymede/state.py` persists run, slices, attempts, Aristotle project and task ids, spend, and transcripts under `runs/<run-id>/`; `ganymede resume` picks up an in-flight Aristotle task without resubmitting.
6. DONE: Add slicing. Claude plans slices with dependencies; each is an instruct call on the same Aristotle project; grading decides accept, retry with more detail, handoff, or give up. Detail level rises after every failure.
7. DONE: Add the referee as a third voice on grading and on the final report. Toggle with `GANYMEDE_REFEREE=0` or `--no-referee`.
8. DONE: Add spend and time guards: attempts per slice, Aristotle tasks per run, Claude calls per run, hours per task, hours per run. A tripped guard halts the run and calls `GANYMEDE_NOTIFY_CMD` if set. Not done: a dollar budget, since Aristotle has no published pricing.
9. BLOCKED (needs the professor): Acceptance test on one of his manuscripts end to end.
10. DONE: Tests for the parts that don't need the network. `tests/`, 15 tests, run with `python -m pytest`.

Open questions found while building:
- Ganymede never interrupts a running Aristotle task except on the per-task hour limit. The professor sometimes stops Aristotle mid-search to hand off. Detecting "stuck" from the event stream would need real event logs to look at (step 1).
- All slices run sequentially on one Aristotle project. Independent slices could run on parallel projects, but merging their Lean files back together is unsolved.
- Claude refusal fallbacks are not enabled. Mathematical text should not trigger them; add `fallbacks` per the Claude API docs if it ever does.
