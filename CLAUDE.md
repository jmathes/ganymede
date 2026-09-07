# Ganymede

An automated go-between that carries work between Claude and Aristotle (Harmonic's Lean 4 prover) so a mathematician can formally verify a paper without shuttling tarballs and instructions by hand. Start with README.md for the origin story and design implications, REFERENCE.md for what Aristotle is and how its API works, and TODO.md for the plan.

## Conventions

- Markdown files use one line per paragraph and per bullet, no hard wrapping.
- The professor who inspired the project is anonymized in every committed file. Refer to him as "the professor." Personal details live in CLAUDE.local.md, which is gitignored.
- REFERENCE.md claims about the Aristotle SDK were verified by reading `aristotlelib` source. When the SDK version changes, re-check before relying on them.
- Python. Use a venv; do not install into the system interpreter.
- Commit only when asked.
