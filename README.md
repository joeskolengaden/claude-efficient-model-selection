# claude-efficient-model-selection

**Stop your subagents from all running on the most expensive model by default.**

A one-skill Claude Code plugin: whenever Claude delegates work — the `Agent` tool, an `agent()`
call in a `Workflow` script, or any multi-step task with pieces of different difficulty — this
skill gives it a concrete rubric for picking the cheapest tier (Haiku → Sonnet → Opus → Fable)
that reliably does that specific piece of work, instead of defaulting to the most capable one
across the board. It also requires Claude to tell you which tier it used whenever it reports
delegated work back to you, so the choice is visible instead of silent.

It does **not** touch your own conversation's model — that's still entirely your call via
`/model`. This only governs the models Claude hands work *to*.

Full guidance: [`plugins/efficient-model-selection/skills/efficient-model-selection/SKILL.md`](plugins/efficient-model-selection/skills/efficient-model-selection/SKILL.md)

## What it actually does, once installed

Nothing to invoke, nothing to configure. It's a standing rule, not a command:

- **Selection:** before Claude spawns a subagent or writes a `Workflow` step, it consults this
  skill's four-tier rubric and picks the cheapest tier that genuinely fits the task, splitting
  mixed-difficulty work across tiers rather than running the whole batch on one model.
- **Reporting:** whenever Claude reports back on delegated work, it states which tier handled it
  — e.g. "ran on Haiku" — as part of that report, not just the result on its own.
- **Generation, not just tier:** where a specific model ID is settable (a `Workflow` script's
  `agent()` `opts.model`), it also prefers an older still-available generation over the newest one
  when the task doesn't need whatever the newest generation added.

You can always override it in the moment — "use Opus for this one" — a direct instruction always
wins over the skill's default.

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
```

Built per the official schema in [Create and distribute a plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces).

## License

MIT — see [LICENSE](LICENSE).
