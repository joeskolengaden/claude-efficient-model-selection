# claude-efficient-model-selection

**Stop your subagents from all running on the most expensive model by default.**

A one-skill Claude Code plugin: whenever Claude delegates work — the `Agent` tool, an `agent()`
call in a `Workflow` script, or any multi-step task with pieces of different difficulty — this
skill gives it a concrete rubric for picking the cheapest tier (Haiku → Sonnet → Opus → Fable)
that reliably does that specific piece of work, instead of defaulting to the most capable one
across the board. It also requires Claude to tell you which tier it used *and why* whenever it
reports delegated work back to you, honor a direct request to use a different model immediately
with no pushback, and escalate one tier up — on its own, without being asked — if a chosen tier's
result turns out inadequate for the task.

It does **not** touch your own conversation's model — that's still entirely your call via
`/model`. This only governs the models Claude hands work *to*.

Full guidance: [`plugins/efficient-model-selection/skills/efficient-model-selection/SKILL.md`](plugins/efficient-model-selection/skills/efficient-model-selection/SKILL.md)

## What it actually does, once installed

Nothing to invoke, nothing to configure. It's a standing rule, not a command:

- **Selection:** before Claude spawns a subagent or writes a `Workflow` step, it consults this
  skill's four-tier rubric and picks the cheapest tier that genuinely fits the task, splitting
  mixed-difficulty work across tiers rather than running the whole batch on one model. This applies
  in every delegation scenario by default, not just when you ask for it explicitly.
- **Reporting, with reasoning:** whenever Claude reports back on delegated work, it states which
  tier handled it *and a short reason why* — e.g. "ran on Haiku (mechanical file listing, no
  judgment needed)" — not just a bare tier name. The reason is what lets you actually judge whether
  the choice was reasonable, rather than just taking it on faith.
- **You can always override it:** say "use Opus for this one" before delegating, "redo that on a
  better model" after seeing a result, or set a standing floor like "always use Sonnet minimum" for
  the session — any of these wins immediately, no pushback, no "are you sure a cheaper tier won't
  work" — that would defeat the point of you having control over the cost/quality tradeoff.
- **Escalates on its own when a tier fails:** if a subagent reports it couldn't complete the task,
  or the output turns out wrong/incomplete when checked, Claude retries the same piece exactly one
  tier up (Haiku → Sonnet → Opus → Fable) and says so plainly — which tier failed, why, what it's
  retrying on. This isn't a silent retry loop; the escalation is visible the same way the original
  choice is.
- **Generation, not just tier:** where a specific model ID is settable (a `Workflow` script's
  `agent()` `opts.model`), it also prefers an older still-available generation over the newest one
  when the task doesn't need whatever the newest generation added.
- **Suggests (never forces) a main-conversation model change:** there's no tool to switch the
  model you're currently talking to — only `/model`, which you run yourself. If the task's
  character clearly shifts mid-conversation (routine → real architecture/ambiguity, or the
  reverse), Claude asks once, in one line, and doesn't repeat a suggestion you've already declined.
- **Logs every delegation for savings reporting:** each `Agent`/`Workflow` call appends its tier
  and token count to `~/.claude/tools/model-selection-log.jsonl`. Ask "how much has this saved?"
  anytime, or run the standalone report script yourself — see [Tracking savings](#tracking-savings)
  below.

## Install

Claude Code exposes the same plugin system across the CLI, desktop app, and IDE extensions, but
in practice the install *path* differs by surface — use whichever matches where you're running.

### CLI, IDE extensions (VS Code / JetBrains)

Type as a chat message (or run as a shell command with `claude` prefixed):

```
/plugin marketplace add joeskolengaden/claude-efficient-model-selection
/plugin install efficient-model-selection@claude-efficient-model-selection
/reload-plugins
```

Non-interactive / scripted:

```sh
claude plugin marketplace add joeskolengaden/claude-efficient-model-selection
claude plugin install efficient-model-selection@claude-efficient-model-selection
```

Once installed, it loads automatically every session — nothing to invoke by name.

### Desktop app ("Claude")

The desktop app's built-in **Skills → Browse** search only searches Anthropic's own curated
directory, not arbitrary GitHub repos, so a custom marketplace like this one won't turn up there.
The confirmed-working path is a manual upload instead:

1. Download **[`efficient-model-selection.skill`](https://github.com/joeskolengaden/claude-efficient-model-selection/raw/main/efficient-model-selection.skill)**
   from this repo (a plain zip — see [Building the `.skill` file](#building-the-skill-file-yourself)
   to build it yourself instead of trusting a downloaded binary, if you prefer).
2. In the app: **Settings → Customize → Skills → Add ▾** → choose the upload/import option → select
   the downloaded `.skill` file.

The `/plugin marketplace add` chat command shown above is documented by Anthropic to work
identically in the desktop app — if you'd rather try that first, it should work the same way; we
just haven't specifically confirmed it end-to-end in this app's chat UI, whereas the manual upload
above is verified working.

**Note on updates:** the manual `.skill` upload is a static snapshot, not a live link to this repo.
If this skill is updated later, re-download and re-upload it to pick up the change — it won't
auto-sync the way a CLI plugin install does.

### Building the `.skill` file yourself

No dependencies beyond Python's standard library:

```sh
git clone https://github.com/joeskolengaden/claude-efficient-model-selection.git
cd claude-efficient-model-selection
python3 - <<'EOF'
import zipfile, os
from pathlib import Path

src = Path("plugins/efficient-model-selection/skills/efficient-model-selection")
out = Path("efficient-model-selection.skill")

with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "node_modules")]
        for f in files:
            if f == ".DS_Store" or f.endswith(".pyc"):
                continue
            full = Path(root) / f
            zf.write(full, Path(src.name) / full.relative_to(src))

print("wrote", out)
EOF
```

Then upload the resulting `efficient-model-selection.skill` as in step 2 above.

### Verifying it's active

- **CLI:** it appears in the available-skills listing at the start of a session.
- **Desktop app:** it appears in **Settings → Customize → Skills**, alongside any built-in ones.
- **Either way:** delegate something and check the report — you should see a tier named (e.g. "ran
  on Haiku") alongside the result. If you never see that, the skill isn't loaded.

## Why this exists

The default instinct when delegating is to reach for the most capable model "to be safe." Most
delegated work doesn't need that: listing files, running a script and reading its output, a
focused refactor, a synthesis pass over a few sources — these have clear procedures and checkable
outcomes, and a cheaper/faster model handles them exactly as well. Defaulting to the top tier for
all of it just spends more time and cost on work that didn't need it.

Validated with live test delegations spanning the range — a mechanical file listing (Haiku, 8.6s,
1 tool call), a synthesis task (Sonnet, 7.2s, 1 tool call), and a genuinely ambiguous judgment call
that required real research (Opus, 154s, 8 tool calls — and produced a substantively better answer
for it). None of the three needed Fable, and the one task that needed real depth got noticeably
more effort than the other two, which is the rubric working as intended, not a uniform shortcut.

The escalation behavior was tested honestly, not staged: two separate attempts to deliberately
trip up a Haiku-tier response (one with a subtle off-by-one trap in some notification-repeat
logic, one a genuine tradeoff judgment call) both came back correct. No fabricated failure was
used to force a demo — that's a real result, and it says the rubric's Haiku tier is more capable
on these probes than the "cheap tier" label might suggest. The escalation instructions are in
place and will fire the next time a chosen tier's output is genuinely inadequate; this round just
didn't happen to produce one.

## Tracking savings

The delegation log at `~/.claude/tools/model-selection-log.jsonl` isn't session-scoped — it's a
global file that keeps growing across every future session and project. Logging itself costs
**zero AI credits**: `model-selection-log-extract.py` reads delegation data (tier, tokens,
duration) directly out of Claude Code's own session transcripts on disk — plain file parsing, not
an extra tool call Claude makes after every delegation. An earlier version of this skill did have
Claude log inline via a tool call, which meant paying token cost on every single delegation just
to record that delegation; that's gone now.

```sh
# One-time setup — runs extraction then sync every hour, plus once immediately on
# login/restart to catch up anything that piled up while the machine was asleep or off:
./model-selection-hourly-update-install.sh

# Read it anytime — this part was already zero-cost, unchanged:
python3 model-selection-report.py              # overall summary
python3 model-selection-report.py --by-day      # + a breakdown per day
python3 model-selection-report.py --by-month    # + a breakdown per month
python3 model-selection-report.py --by-host     # + a breakdown per machine (hostname)
python3 model-selection-report.py --by-user     # + a breakdown per local username
python3 model-selection-report.py --by-project  # + a breakdown per project
```

`model-selection-hourly-update.sh` runs extraction and the private-backup sync (below) as one
combined job — extraction always finishes before sync reads the file, rather than two
independently-scheduled jobs that could race or drift apart. Both steps are incremental, so a run
after any length of gap (including the immediate one on login/restart) just processes everything
that piled up since the last successful run, in one pass.

**Multi-account safe by construction:** everything lives under `~/.claude/...`, so on a Mac with
several macOS user accounts, each account's transcripts, log, and scheduled job are already
isolated by the filesystem — there's no cross-account data path to worry about. The one thing that
*isn't* automatic is the job itself: launchd plists need literal paths baked in (no `$HOME`
expansion), so `model-selection-hourly-update-install.sh` generates one scoped to whichever
account runs it, rather than shipping a plist hardcoded to one person's home directory. Each
account that wants this needs to run the install script once, under its own login.

**Scope note:** the extractor currently covers foreground `Agent`-tool delegations
(`run_in_background: false`) that explicitly set a model tier — everything this skill actually
governs. Background `Agent` calls and `Workflow` `agent()` calls aren't covered yet; a delegation
made that way won't appear in the log until the extractor is extended for those shapes.

Each entry also carries `duration_ms`, `tool_uses`, and `escalated_from` (which tier failed
first, if this was an escalation retry — see § "Escalate when a tier fails the task") — all read
straight from the delegation's own result, no extra cost. Plus a deliberately bounded
identity/context set: `hostname`, `os`, `username`, `project` (folder name only, never the full
path), and `utc_offset` — a rough regional signal computed entirely from the local system clock,
with no network call and no third-party IP lookup. None of this is a device fingerprint, and
nothing further should be added — no full IP address, MAC address, hardware identifiers, or full
file paths — without an explicit, specific ask naming the exact field. See the skill's `SKILL.md`
§ "Track delegations, report savings" for the full reasoning, including why `utc_offset` was
chosen over IP-based geolocation specifically.

**Backing this data up:** `model-selection-hourly-update.sh` already calls a sync step after
extraction — but the sync *target* is a personal, private repo, not this one, so setting that part
up is on you. This repo is the public, shareable skill; the log is personal usage data and
shouldn't live alongside it.

`multi-contributor-sync-template/sync.sh` is a working reference for that sync step — point it at
your own **private** GitHub repo (`git remote add origin <your-private-repo-url>` inside a fresh
clone of it) and it's ready to use. It's **merge-safe, not overwrite-and-push**: if more than one
person contributes to the same private repo, a plain copy-and-push would let one person's push
silently clobber another's, or fail outright once two people push around the same time. This
script instead pulls the latest remote state, takes the deduplicated union of (remote entries) +
(your own local entries), and pushes — retrying the pull/merge/push cycle if someone else pushed
in between. Validated with a real simulated-concurrent-push test, not just assumed to work.

**A dashboard, if more than one person is contributing:** add a small GitHub Action to your
private repo that regenerates a README section (overall stats, plus a per-contributor breakdown
once there's more than one) on every push to the log — visible the moment anyone opens the repo,
no separate hosting needed. GitHub Pages would be the more visual option, but it needs a paid plan
to work on a private repo; a README table works on any plan. Not included here for the same reason
as the sync script — it depends on the private repo's own structure, which is yours to set up.

No dependencies beyond Python's standard library. Sample output:

```
=== Overall (10 delegations) ===
  haiku      6 calls,   171,839 tokens
  opus       2 calls,   101,126 tokens
  sonnet     2 calls,    85,019 tokens
  Actual cost:            $2.7976
  Counterfactual (opus):  $5.3698
  Estimated savings:      $2.5722  (47.9% reduction)
  Token-equivalent:       171,478 opus tokens (what the savings would buy at opus's rate)
```

The counterfactual baseline is Opus, not Fable — Opus is the documented no-skill default for
delegated work, so it's the honest comparison rather than the most flattering one. Cost is an
estimate: each logged entry carries one blended token count with no input/output split, so it's
priced at each tier's average of its input and output rate, not exact per-token billing. See the
constants at the top of the script if pricing changes and you want to update the rates.

## Updating / uninstalling (CLI / IDE)

```
/plugin marketplace update claude-efficient-model-selection
/plugin uninstall efficient-model-selection@claude-efficient-model-selection
/plugin marketplace remove claude-efficient-model-selection
```

For the desktop app, re-download and re-upload the `.skill` file to update; remove it from
**Settings → Customize → Skills** to uninstall.

## Structure

```
.claude-plugin/marketplace.json                                              marketplace catalog
plugins/efficient-model-selection/.claude-plugin/plugin.json                 plugin manifest
plugins/efficient-model-selection/skills/efficient-model-selection/SKILL.md  the skill itself
build.sh                                                                     rebuilds the .skill package
model-selection-log-extract.py                                               zero-cost delegation logger — see Tracking savings
model-selection-hourly-update.sh                                             runs extraction + private-backup sync, in that order
model-selection-hourly-update-install.sh                                     installs the hourly job for the current account
model-selection-report.py                                                    standalone savings report — see Tracking savings
multi-contributor-sync-template/sync.sh                                      merge-safe sync reference for a shared private log repo
.github/workflows/verify-skill-package.yml                                   CI: fails loudly if the .skill goes stale
```

Built per the official schema in [Create and distribute a plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces).

### After editing SKILL.md

Run `./build.sh` and commit the regenerated `efficient-model-selection.skill` alongside it. CI
checks this on every push/PR that touches either file — it verifies the packaged content matches
the source and that the description stays under the desktop app's 1024-char limit, and fails the
check if either drifts. It's deliberately verify-only rather than auto-rebuilding: this repo isn't
persistently cloned anywhere a commit hook could live, and `zip` output isn't byte-reproducible
(embeds mtimes), so an auto-rebuild-on-commit hook would churn the binary on every commit,
including ones that don't touch the skill at all. A loud failure on a real staleness bug is the
right amount of machinery for a repo touched a handful of times a year by one person.

## License

MIT — see [LICENSE](LICENSE).
