1. Get an Aristotle API key and run one job by hand: submit a Lean project with sorries, watch the event stream, download the tarball, inspect it. Confirm agent questions actually fire with `TIMEOUT_15_MIN` and can be answered from code.
2. Collect David's current artifacts: one real slicing prompt, one Claude grading of an Aristotle result, one "Claude handoff" exchange. These are the spec for the orchestrator's prompts.
3. Define "done" for a slice and for a paper. At minimum: no `sorry`, `#print axioms` shows nothing beyond the standard set, and the main theorem statement has been compared against the paper's claim and approved.
4. Build the smallest loop with no slicing: Lean project in, Aristotle runs, Claude answers Aristotle's questions, tarball out, Claude grades it. One file, run locally.
5. Make it resumable. Persist paper, Aristotle project id, slice history, and transcripts on disk so a crash or reboot mid-run doesn't lose hours of work.
6. Add slicing: Claude proposes slices, each becomes an instruct call on the same Aristotle project, grading decides whether to advance, retry with more detail, or hand off.
7. Add the referee as a third voice on grading and on handoff instructions.
8. Add spend and time guards: Claude tokens per slice, Aristotle tasks per paper, and a hard stop that notifies David instead of looping forever.
9. Acceptance test: David runs it on one of the 25 manuscripts end to end.
10. Tests for the parts that don't need the network: state persistence, done-check on a tarball, prompt assembly.
