# Getting started

This walks through installing Ganymede on a Mac or Linux machine and running it on a paper. It assumes you can open a terminal and paste commands, and nothing else. Each step ends with a way to confirm it worked.

## 1. Get the three accounts you need

**Aristotle** (the prover). Go to https://aristotle.harmonic.fun and log in with Google. Then open https://aristotle.harmonic.fun/dashboard/keys and create an API key. Copy it somewhere safe right away; the dashboard may not show it again. It is free at the time of writing.

**Claude** (the mathematician and referee). You need one of:

- A Claude Pro or Max subscription plus the Claude Code command-line tool, logged in. Install it from https://code.claude.com/docs/en/setup, then run `claude` once in a terminal and follow the login prompts. Ganymede will use that login. Or:
- An Anthropic API key from https://console.anthropic.com. This bills per use, separately from a subscription.

**GitHub** is not required. You only need it to download this repository, which you can also do as a zip file.

## 2. Install the tools

Open a terminal and run these one at a time.

Git and curl (Ubuntu/Debian; on a Mac these come with Xcode command line tools, run `xcode-select --install`):

```bash
sudo apt install git curl
```

Lean is optional. Ganymede never runs it; Aristotle builds everything on its own servers. Install it only if you want to open the results yourself. Via its version manager elan, accepting the defaults when asked:

```bash
curl https://elan.lean-lang.org/elan-init.sh -sSf | sh
source ~/.elan/env
lake --version
```

You should see a version line. If a later terminal says `lake: command not found`, run `source ~/.elan/env` again or open a new terminal.

Python 3.12 or newer. Check with:

```bash
python3 --version
```

If it is older than 3.12, install a newer one from https://www.python.org/downloads/ or with your package manager.

## 3. Download Ganymede and set up its Python environment

```bash
git clone https://github.com/jmathes/ganymede.git
cd ganymede
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
ganymede --help
```

You should see a list of commands: run, resume, status, doctor, check. Every later step assumes you are in the `ganymede` directory with the environment active. If you open a new terminal, run `cd ganymede && source .venv/bin/activate` first.

(If you use conda, `scripts/sync-env.sh` creates a conda environment named ganymede instead of the `.venv` above.)

## 4. Put your keys in place

```bash
cp .env.example .env
```

Open `.env` in any text editor and paste your Aristotle key after `ARISTOTLE_API_KEY=`, with no spaces or quotes. If you are using an Anthropic API key rather than a Claude subscription, uncomment the `ANTHROPIC_API_KEY=` line and paste it there too. Save the file. It is ignored by git so it will never be uploaded.

Now check everything:

```bash
ganymede doctor
```

Every line should say `ok`. If one says `FAIL`, it also says what to do. Run `ganymede doctor` again after fixing it. The Claude check makes one tiny request, so it takes a few seconds.

## 5. Run it on a paper

A good first run is the toy example that ships with the repo: a two-theorem "paper" and a matching Lean project with the proofs left as `sorry`. It needs no Mathlib, so it finishes in a few minutes:

```bash
ganymede run --paper examples/toy/paper.md --lean-project examples/toy
```

A second warm-up uses Mathlib, the way a real paper will. The "paper" is one sentence, `There are infinitely many prime numbers.`, and Ganymede has to plan the whole proof itself:

```bash
ganymede run --paper examples/primes/infinite_primes.md
```

For a real paper, Ganymede takes a text file: LaTeX source (`.tex`), Markdown, or plain text. A PDF will not work; export the source. Then:

```bash
ganymede run --paper /path/to/paper.tex
```

That creates a fresh Lean project pinned to the Mathlib version Aristotle supports, asks Claude to plan the verification, and starts the loop. The project is created inside the run directory (see below), never next to your paper, and its name on Aristotle's dashboard is the paper's filename plus part of the run id. If you already have a Lean project for the paper, add `--lean-project /path/to/project` and Ganymede works inside it instead.

### What a run looks like

Everything Ganymede decides or learns is printed as it happens, in labelled blocks:

- `PAPER SUMMARY`, `MAIN CLAIMS`, and one `SLICE` block per slice: Claude's plan. The main claims are the yardstick for the whole run; read them and make sure they are what you meant.
- `ARISTOTLE PROJECT CREATED`: the project id, a link to it on Aristotle's dashboard where you can watch the same job, and the `aristotle show` command that prints its status.
- A warning from the Aristotle SDK that the project has no `.lake` folder. Ganymede prints an explanation just before it. It is expected and harmless for Mathlib projects.
- `INSTRUCTIONS TO ARISTOTLE`: the exact text sent, with the detail level. Level 0 is terse; it rises after each failed attempt.
- Aristotle's own event stream: its thinking, the shell commands it runs, files it edits, and any question it asks (`ARISTOTLE ASKS`, followed by Claude's `ANSWER`).
- `ARISTOTLE'S SUMMARY`, then `LEAN CHECK`: what came back, whether any `sorry` or `axiom` remains, and every theorem statement verbatim.
- `GRADE`: accept, retry, handoff, or give up, with the statement-fidelity judgment and the reasoning. When the referee overrules, its objection is included.
- `FINAL REPORT` at the end, and the halt reason if a guard tripped.

A slice of Euclid's theorem takes Aristotle a few minutes; a research paper takes hours. You can close the terminal; see the next section.

The run's output lives in `runs/<run-id>/`, where the run id is printed at the start and listed by `ganymede status`:

- `REPORT.md` appears at the end and is the thing to read: whether every claim was verified, and any caveats.
- `state.json` is the full record, updated after every step.
- `tarballs/` holds every result Aristotle returned. The last one is the finished Lean project.
- `transcripts/` holds every exchange with Claude, one file each, if you want to see the reasoning.
- `plan.json` is the slice plan, and the project directory named after your paper is what was uploaded to Aristotle.

The run ends in one of three states. `done` means every slice was accepted, every theorem statement was judged to match the paper, and the final project has no `sorry` and no declared axioms. `halted` means a guard tripped or a slice was given up on; the reason is printed and stored, and a human should look. `failed` means a bug or an outage; try `resume`.

## 6. Stopping, resuming, checking on it

```bash
ganymede status                 # one line per run
ganymede status <run-id>        # details of one run
ganymede resume <run-id>        # continue after a crash, a reboot, or a halt
```

Resuming is safe: Ganymede remembers which Aristotle task was in flight and picks it up rather than starting over. Pressing Ctrl-C leaves Aristotle running on its server; resume reconnects to it. You can also watch or cancel the job on Aristotle's dashboard at the link Ganymede printed.

To be told when a run finishes or halts instead of watching the terminal, set a command in `.env` that will receive the message on standard input, for example `GANYMEDE_NOTIFY_CMD=mail -s ganymede you@example.com`.

## 7. Knobs you might want

All are environment variables you can put in `.env`:

- `GANYMEDE_MAX_ATTEMPTS` (default 4): tries per slice before giving up on it.
- `GANYMEDE_MAX_TASKS` (default 40): Aristotle jobs per run.
- `GANYMEDE_MAX_TASK_HOURS` (default 10): how long one Aristotle job may run before it is cancelled and Claude is asked for more detailed instructions.
- `GANYMEDE_MAX_RUN_HOURS` (default 72): total time before the run halts.
- `GANYMEDE_REFEREE=0`: turn off the skeptical referee, which halves Claude usage at some cost in caution.
- `GANYMEDE_MODEL`: which Claude to use. Default `claude-opus-5`.

## 8. When something looks wrong

- The main claims Claude extracted are not what the paper claims: stop the run and rewrite the paper's statement of results to be unambiguous, then start a new run. Everything downstream depends on those claims.
- A grade says a theorem statement `differs` from the paper: that is the check working. Read the fidelity notes in the `GRADE` block or in `runs/<run-id>/transcripts/`.
- The run halted with `blocked slices`: Aristotle could not do a slice even with Claude's most detailed instructions. The last attempt's instructions and Aristotle's summary, both in the transcripts, show where it got stuck. This is where a human mathematician earns their keep.
- Anything that looks like a crash: `ganymede resume <run-id>`, and if it recurs, keep the terminal output.

## 9. Checking any Aristotle result by hand

If you have a tarball from Aristotle from anywhere, not just from Ganymede:

```bash
ganymede check result.tar.gz
```

It lists remaining sorries, declared axioms, and every theorem statement, so you can compare them to what the paper claims. Exit code 0 means clean.
