---
name: efficient-model-selection
description: Standing guidance for picking which model tier (Haiku, Sonnet, Opus, or Fable) to run a delegated task on — via the Agent tool's model parameter, a Workflow script's agent() calls, or any multi-step task with pieces of different difficulty. Consult this BEFORE spawning any subagent or authoring a Workflow, not just when the user says "efficiently" — it applies by default to every delegation, no exceptions. Reserves Fable for work needing deep, ambiguous, or high-stakes reasoning; defaults everything else to a cheaper tier. Also governs: reporting which tier was used and why every time delegated work is reported back; honoring a direct user override immediately; and escalating one tier up when a chosen tier's result turns out inadequate. Does not apply to the main conversation's own model, set via /model.
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

**Default down when unsure.** If you can't immediately tell whether a task is Sonnet or Opus, start
with the cheaper tier — this costs less overall than defaulting every uncertain case to the
expensive tier "to be safe." See "Escalate when a tier fails the task" below for what to do if that
bet doesn't pay off.

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

## Report the choice — and why — back to the user

Picking the right tier is only half of this — the user generally can't see which model a
delegated call used just from the tool call itself. When you report the result of delegated work
back to the user (a subagent's findings, a Workflow's output), state which tier handled it *and a
short reason why*, as part of that report — e.g. "ran on Haiku (mechanical file listing, no
judgment needed)" / "the synthesis step used Sonnet (weighing a few sources), the judgment call
used Opus (real ambiguity in the tradeoffs)". A tier name alone doesn't let the user tell whether
the choice was reasonable; the reason is what makes it checkable. Keep it to a clause, not a
paragraph — this is a tag alongside the result, not a justification essay. Do this by default,
every time, not only when asked.

## The user can always override

A direct instruction about which model to use always wins, immediately, no pushback — this
overrides the rubric outright, not just as a tiebreaker. This applies whether the instruction comes:

- **Before delegating** — the user says "use Opus for this" before you've made a choice: use Opus,
  don't re-litigate whether the rubric would have picked something cheaper.
- **After seeing a report** — the user says "redo that on a better model" after seeing a Haiku or
  Sonnet result: re-run the same task one or more tiers up as requested, don't defend the original
  choice.
- **As a standing preference for the session** — the user says something like "always use Sonnet
  minimum" or "don't delegate to Haiku today": treat that as the effective floor for every
  delegation until they say otherwise, silently overriding what the rubric alone would have picked.

Don't ask for confirmation before honoring an override — asking "are you sure, the rubric suggests
a cheaper tier would work" defeats the point of giving the user control over their own cost/quality
tradeoff.

## Escalate when a tier fails the task

Choosing a tier isn't a one-shot bet — if the result turns out inadequate for what the task
actually needed, that's a signal to escalate, not to accept the result or silently retry the same
tier again. This applies any time a chosen tier's output falls short, not only in the "I wasn't
sure which tier to pick" case.

**What counts as a failure worth escalating:**
- The subagent reports it couldn't complete the task, or hit something beyond its judgment.
- You check the output against the actual requirement (or the user does) and it's wrong, incomplete,
  or missed something material — not just stylistically different from how you'd have done it.
- The user says the result is wrong or insufficient.

**How to escalate:**
- Move exactly one tier up from what was used (Haiku → Sonnet → Opus → Fable) and re-run the
  specific failed piece — not the whole batch if only one part failed.
- State plainly what happened when you report back: which tier failed, why, and which tier you're
  retrying on. This isn't a silent retry — the user should be able to see the escalation happened,
  same as any other tier choice.
- Fable is the ceiling — there's nothing to escalate to above it. If a Fable attempt is also
  inadequate, that's a real blocker to surface to the user (the task may need a different approach
  entirely, not just more model), not something to loop on.

This is the other half of "default down when unsure" below: starting cheap only pays off if you
actually notice and correct a bad result, rather than letting it stand because escalating feels
like admitting the first choice was wrong. It wasn't wrong — starting cheap and escalating on
evidence is the efficient strategy, not a fallback for a mistake.

## Quick reference

| Signal | Tier |
|---|---|
| Clear procedure, checkable output, little judgment | Haiku |
| Multiple interacting steps, a few tradeoffs to weigh | Sonnet |
| Real ambiguity, conflicting inputs, costly if wrong | Opus |
| Deepest reasoning needed, or a documented cheaper-tier failure | Fable |
| Unsure which tier | Start one cheaper, escalate only the failing piece |
| Task fits an older generation you know is available | Prefer it over the newest generation of that tier |
| Chosen tier's result is inadequate | Escalate exactly one tier up, state why, re-run only the failed piece |
| User names a model or tier directly | Honor it immediately, no pushback, overrides the rubric |
