# Ganymede

An automated go-between that carries work between Claude and Aristotle (Harmonic's Lean 4 prover) so a mathematician can formally verify a paper without shuttling tarballs and instructions by hand. Start with README.md for the origin story and design implications, REFERENCE.md for what Aristotle is and how its API works, and TODO.md for the plan.

## Conventions

- Markdown files use one line per paragraph and per bullet, no hard wrapping.
- The professor who inspired the project is anonymized in every committed file. Refer to him as "the professor." Personal details live in CLAUDE.local.md, which is gitignored.
- REFERENCE.md claims about the Aristotle SDK were verified by reading `aristotlelib` source. When the SDK version changes, re-check before relying on them.
- Python 3.12 in a conda env named `ganymede` on the local machine (not in the repo). `scripts/sync-env.sh` creates it and installs requirements.txt; `scripts/sync-env.sh add PKG` installs a package and re-freezes requirements.txt. Never pip install into the env by hand without re-freezing.
- Commit only when asked.

## Layout

- `ganymede/orchestrator.py` is the loop; it does no math and calls no SDK directly.
- `ganymede/advisor.py` is the Claude side (mathematician and referee roles, structured outputs). Two backends: `ClaudeCodeAdvisor` shells out to `claude -p --json-schema` and uses the subscription login (default); `ClaudeAdvisor` uses the Anthropic SDK and an API key. `ganymede/formalizer.py` is the Aristotle side. Both have a Protocol and a fake; tests use the fakes.
- `ganymede/lean_check.py` is the static definition of done. `ganymede/state.py` is the on-disk run state.
- `ganymede/prompts/*.md` are the role system prompts. They are the most likely thing to need tuning once real transcripts exist.
- Run tests with `python -m pytest` inside the env. They need no network or API keys.
