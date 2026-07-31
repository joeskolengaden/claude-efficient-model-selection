---
name: efficient-model-selection
description: Standing guidance for picking which model tier (Haiku, Sonnet, Opus, or Fable) to run a delegated task or sub-task on — via the Agent tool's model parameter, a Workflow script's agent() calls, or when planning any multi-step task whose pieces differ in difficulty. Consult this BEFORE spawning any subagent or authoring a Workflow, not just when the user says "efficiently" or "cheaply" — it applies by default to every delegation decision. Reserves the most capable/expensive tier (Fable) for work that genuinely needs deep, ambiguous, or high-stakes reasoning, and defaults everything else to a cheaper, faster tier. Also governs reporting: state which tier was used whenever delegated work is reported back to the user, every time, not just when asked. Does not apply to the main conversation's own model, which the user sets directly via /model.
---

# Efficient model selection for delegated work

Every time you're about to hand a task to a subagent — an `Agent` call, an `agent()` call inside a
`Workflow` script, or even just deciding how to break up a multi-step job — you're making a model
choice. The default instinct is to reach for the most capable model "to be safe." Resist that. Most
delegated work does not need maximum capability, and defaulting to it wastes cost and time on tasks
that a cheaper, faster model handles just as well. Efficiency is the goal, not a fallback.

## The four tiers, and what actually belongs on each

Think of this as a ladder. Start by asking what the task *genuinely* requires, not what would be
"nice to have." A task doesn't earn a more expensive tier just because it's part of something
important — an important task made of routine steps still runs its steps on cheap tiers.

**Haiku — routine, mechanical, narrow-scope work.**
The task has a clear procedure and a checkable outcome; there's little judgment to exercise.
- Listing/finding files, grepping for a symbol, reading a known location
- Running a script or CLI tool and reporting/parsing its output
- Fetching a URL or API response and summarizing it factually
- Straightforward verification passes (does X exist, does Y match, run this check and report pass/fail)
- Benchmarking or timing runs where the "thinking" is in the harness, not the agent
- Mechanical edits with fully-specified instructions (rename this, apply this exact diff pattern N times)

**Sonnet — moderate complexity, some synthesis or judgment required.**
The task involves more than one step where the steps interact, or requires weighing a few options.
- Multi-file code changes where the files need to stay consistent with each other
- Research that needs synthesis across several sources, not just retrieval
- Design exploration with a handful of clear tradeoffs
- Code review passes, focused refactors, writing tests against existing behavior
- This is the right *default* when you're unsure and the task isn't obviously Haiku-simple

**Opus — stronger judgment, ambiguity, or consequence.**
The task has real ambiguity to resolve, conflicting inputs to reconcile, or getting it wrong is
costly.
- Architectural or design decisions with long-lived consequences
- Multi-step planning where the steps aren't obvious upfront and depend on each other
- Synthesizing genuinely conflicting findings from multiple sources/agents
- High-stakes verification (the kind where a missed issue matters, not just a style nit)

**Fable — reserve this. It is the exception, not the default.**
Use it only when the task needs the deepest reasoning available, or when a cheaper tier already
tried and the result was genuinely inadequate (not just "could be a bit better"). Concretely: deep
ambiguous synthesis with no clear framework to apply, decisions that are expensive or impossible to
reverse if wrong, or an escalation after a documented failure at a cheaper tier. "This task matters
a lot to the user" is not by itself a reason to reach for Fable — most important tasks are well
within Sonnet's or Opus's range. If you're reaching for Fable, be able to say in one sentence why
Opus specifically wouldn't be enough.

## How to apply this

**Split before you assign.** When a task has sub-tasks of different difficulty, don't run the whole
batch on one model picked for the hardest part. Break it up and give each piece its own tier — e.g.
a workflow that fetches data (Haiku), synthesizes it into a report (Sonnet), and makes a judgment
call about what to do with the findings (Opus) should use three different `model` values, not one.

**Default down when unsure, escalate on evidence.** If you can't immediately tell whether a task is
Sonnet or Opus, start with the cheaper tier. If the result is inadequate, re-run the specific failed
piece one tier up — this costs less overall than defaulting every uncertain case to the expensive
tier "to be safe," and you only pay for the extra capability on the pieces that actually needed it.

**In the `Agent` tool:** pass `model: "haiku" | "sonnet" | "opus" | "fable"` per call, chosen per
the rubric above. Omitting it inherits the session's main-loop model — do this only when you
actually want that (e.g. the task needs the exact capability level the user is currently running
at), not as a default to avoid deciding.

**In a `Workflow` script:** set `opts.model` on each `agent()` call individually. A pipeline stage
that greps logs and a stage that synthesizes a root-cause hypothesis from those logs are different
tasks with different tiers — don't let one `model` choice at the top of the script apply uniformly
to both.

**What this does NOT cover:** the main conversation's own model is the user's choice, set via
`/model`. This skill governs delegation-time decisions only — the models you hand work *to*, not
the model you're currently running as.

## Older generations count too — tier isn't the only efficiency lever

"Newest" and "most capable" are not the same axis as "right for this task." A previous-generation
model at the tier you need can be the more efficient choice when the task doesn't require whatever
the newest generation added — treat generation the same way you treat tier: pick the cheapest one
that reliably does the job, not the newest one available.

- The `Agent` tool's `model` parameter only exposes tier names (`haiku`/`sonnet`/`opus`/`fable`) and
  resolves each to its current default generation — there's no version pinning available there.
- A `Workflow` script's `agent()` takes `opts.model` as a free-form string, which can name a specific
  model ID rather than just a tier — that's where generation choice is actually actionable. If you
  know (from the system prompt or explicit context) that an older, still-available generation exists
  at the tier a sub-task needs, prefer it over the newest generation of that tier when the task is
  well within what the older generation reliably handled — don't reach for the newest generation by
  default any more than you'd reach for a bigger tier by default.
- Don't guess at model ID strings you're not confident are valid — an unrecognized ID fails the call.
  Only pin an older generation when you have it from context (the system prompt, or the user telling
  you what's available); otherwise let the tier resolve to its current default.

## Report the choice back to the user

Picking the right tier is only half of this — the user generally can't see which model a
delegated call used just from the tool call itself. When you report the result of delegated work
back to the user (a subagent's findings, a Workflow's output), state which tier handled it as part
of that report — e.g. "ran on Haiku" / "the synthesis step used Sonnet, the judgment call used
Opus" — not as a separate aside, just a short tag alongside the result. Do this by default, every
time, not only when asked. This is what makes the tier choice a decision the user can actually see
and correct, rather than one made silently on their behalf.

## Quick reference

| Signal | Tier |
|---|---|
| Clear procedure, checkable output, little judgment | Haiku |
| Multiple interacting steps, a few tradeoffs to weigh | Sonnet |
| Real ambiguity, conflicting inputs, costly if wrong | Opus |
| Deepest reasoning needed, or a documented cheaper-tier failure | Fable |
| Unsure which tier | Start one cheaper, escalate only the failing piece |
| Task fits an older generation you know is available | Prefer it over the newest generation of that tier |
