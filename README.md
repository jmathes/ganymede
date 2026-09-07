# Ganymede

Ganymede was cupbearer to the gods. This project is meant to take over carrying water.

Specifically: it is an automated go-between for formally verifying mathematics with
[Aristotle](https://aristotle.harmonic.fun/) (Harmonic's Lean 4 prover) and Claude. The
human currently shuttles tarballs and instructions between the two; Ganymede should do
that instead, including negotiating and renegotiating the division of labor between the
AIs, without needing to understand the mathematics itself.

## Origin

This project came out of a conversation in September 2026 between the author and an old
math professor of his. The relevant parts are transcribed below.

---

**Me:** Hey, while I'm unemployed and looking for things to do with myself, do you have
any ideas? Some website or app or program you wish existed?

**Professor:** Well now that you mention it... I have been using AI lately for mathematical
research. Lately I have been using websites Aristotle and Claude.ai to do formal
verification. The problem is that this keeps me very busy carrying water back and forth
between the two websites.

If I have a long paper, Claude will break the verification down into "slices." The
instructions to Aristotle can be less detailed (meaning that Aristotle had to do a lot of
searching to build the formal proofs) or more detailed. When Aristotle finishes a slice,
I have to save a tarball, upload it to Claude.ai, get an opinion on how well Aristotle
did, then have it generate the next instructions for the next slice, then go back to
Aristotle, upload the new files and paste in the verbal instructions.

My role in this involves almost no mathematical thinking once I've written the initial
paper (Claude and Aristotle will even silently fix my mistakes). But it would be amazing
to have an automated go-between leaving me almost nothing to do but wait for the news
that the verification is bullet-proof.

Aristotle is quite the AI itself, so reasonably able to reflect on its own process. For
example sometimes when the searching is too hard I will ask it if it wants a "Claude
handoff" and if it agrees, I'll stop Aristotle's work, feed Claude.ai a request from
Aristotle, and Claude.ai, which is better at thinking about mathematics in a free-wheeling
way, will cook up more detailed instructions in order to get Aristotle through a
bottleneck.

So a go-between program would need to take my place with respect to negotiating and
dynamically renegotiating the division of labor. But the go-between doesn't have to
understand the mathematics.

**Me:** Aristotle and Claude both have APIs you can use. That would be quite a simple
Python program you could just run locally.

I'm fuzzy on some details. If you have a big verification to work through, wouldn't you
also need a dependency graph for Claude to be able to break off independent chunks? Do
you build those or does Claude? I would be surprised if Claude could do it without some
more formal structure on the data.

**Professor:** Fable is smart enough to do the organization.

**Me:** That's got to be very expensive computationally. If you're not paying a lot for
it, it's being sold to you under market rate prior to planned enshittification. 🙂

**Professor:** I've been at this for just a month. Trying to use AI to polish about 25
manuscripts that have been sitting for years on my hard drives. Amazingly I have made
great progress without knowing anything much about what's happening under the hood.

What reassures me is that if the Lean compiles, that's bullet-proof. The only anxiety is
whether Aristotle has actually proved what I think it has proved, or something else.

I have also found it useful, when doing actual research, to set Claude and ChatGPT
against one another. One is the researcher, one is the referee, and each new attempt to
solve a problem by the researcher gets fed to the very skeptical referee and they fight
it out. The combination seems to be more intelligent than either AI alone. And again...
I'm just carrying water (mostly).

What I have found is that ChatGPT will fall into finding fault with everything... but
Claude will eventually do what any good mathematician would do... and declare the referee
is an idiot. It's really very funny... the insights you get into people by watching these
simulations.

Getting the mathematician, the referee and the formalizer all talking to one another
might produce amazing results.

---

## What this implies for the design

- **Three roles, one orchestrator.** A mathematician (free-wheeling reasoning), a referee
  (skeptical review), and a formalizer (Aristotle, producing Lean). Ganymede is the
  orchestrator and does no math of its own.
- **The loop is a negotiation, not a pipeline.** Aristotle may get stuck and ask for a
  handoff; the mathematician then writes more detailed instructions. The division of
  labor between "let Aristotle search" and "spell it out" has to be adjustable per slice.
- **Statement fidelity is the real risk.** A compiling Lean proof is bulletproof only for
  the theorem as stated in Lean. Both Claude and Aristotle will silently "fix" things.
  Ganymede should check that what got proved is what the paper claims, not just that
  the build is green.

## Known pieces

- Aristotle has a Python SDK and CLI, [`aristotlelib`](https://pypi.org/project/aristotlelib/).
  It accepts a Lean project directory plus natural-language instructions, runs
  asynchronously (minutes to hours), and returns a tarball.
- An existing MCP wrapper, [septract/lean-aristotle-mcp](https://github.com/septract/lean-aristotle-mcp),
  exposes `prove`, `prove_file`, and `formalize` with async polling.
- The Claude side is the Claude API.
