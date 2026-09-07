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

Lean, via its version manager elan. Accept the defaults when asked:

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

For a real paper, Ganymede takes a text file: LaTeX source (`.tex`), Markdown, or plain text. A PDF will not work; export the source. Then:

```bash
ganymede run --paper /path/to/paper.tex
```

That creates a fresh Lean project pinned to the Mathlib version Aristotle supports, asks Claude to plan the verification, and starts the loop. If you already have a Lean project for the paper, add `--lean-project /path/to/project` and Ganymede works inside it instead.

What you will see: log lines as Claude plans, as Aristotle works (its own thinking and commands stream through), and as each slice is graded. This takes anywhere from minutes to many hours depending on the paper. You can close the terminal; see the next section.

The run's output lives in `runs/<run-id>/`, where the run id is printed at the start:

- `REPORT.md` appears at the end and is the thing to read: whether every claim was verified, and any caveats.
- `state.json` is the full record, updated after every step.
- `tarballs/` holds every result Aristotle returned. The last one is the finished Lean project.
- `transcripts/` holds every exchange with Claude, one file each, if you want to see the reasoning.

The run ends in one of three states. `done` means every slice was accepted, every theorem statement was judged to match the paper, and the final project rebuilt locally with no `sorry` and no unexpected axioms. `halted` means a guard tripped or a slice was given up on; the reason is printed and stored, and a human should look. `failed` means a bug or an outage; try `resume`.

## 6. Stopping, resuming, checking on it

```bash
ganymede status                 # one line per run
ganymede status <run-id>        # details of one run
ganymede resume <run-id>        # continue after a crash, a reboot, or a halt
```

Resuming is safe: Ganymede remembers which Aristotle task was in flight and picks it up rather than starting over. Pressing Ctrl-C leaves Aristotle running on its server; resume reconnects to it.

To be told when a run finishes or halts instead of watching the terminal, set a command in `.env` that will receive the message on standard input, for example `GANYMEDE_NOTIFY_CMD=mail -s ganymede you@example.com`.

## 7. Knobs you might want

All are environment variables you can put in `.env`:

- `GANYMEDE_MAX_ATTEMPTS` (default 4): tries per slice before giving up on it.
- `GANYMEDE_MAX_TASKS` (default 40): Aristotle jobs per run.
- `GANYMEDE_MAX_TASK_HOURS` (default 10): how long one Aristotle job may run before it is cancelled and Claude is asked for more detailed instructions.
- `GANYMEDE_MAX_RUN_HOURS` (default 72): total time before the run halts.
- `GANYMEDE_REFEREE=0`: turn off the skeptical referee, which halves Claude usage at some cost in caution.
- `GANYMEDE_MODEL`: which Claude to use. Default `claude-opus-5`.
- `GANYMEDE_LAKE_BUILD=0` or `--no-lake-build`: upload the Lean project without running `lake build` in it first. By default Ganymede builds it so Aristotle receives the project's dependencies; for a Mathlib project that means fetching Mathlib's prebuilt cache, several gigabytes, the first time.
- `GANYMEDE_LOCAL_BUILD=0`: skip rebuilding results with your own Lean after each Aristotle task.

## 8. Checking any Aristotle result by hand

If you have a tarball from Aristotle from anywhere, not just from Ganymede:

```bash
ganymede check result.tar.gz
```

It lists remaining sorries, declared axioms, and every theorem statement, so you can compare them to what the paper claims. Exit code 0 means clean.
