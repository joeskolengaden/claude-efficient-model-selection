# claude-efficient-model-selection

**Stop your subagents from all running on the most expensive model by default.**

A one-skill Claude Code plugin: whenever you delegate work — the `Agent` tool, an `agent()` call
in a `Workflow` script, or any multi-step task with pieces of different difficulty — this skill
gives Claude a concrete rubric for picking the cheapest tier (Haiku → Sonnet → Opus → Fable) that
reliably does that specific piece of work, instead of defaulting to the most capable one across
the board.

It does **not** touch your own conversation's model — that's still entirely your call via
`/model`. This only governs the models Claude hands work *to*.

Full guidance: [`plugins/efficient-model-selection/skills/efficient-model-selection/SKILL.md`](plugins/efficient-model-selection/skills/efficient-model-selection/SKILL.md)

## Install

```
/plugin marketplace add joeskolengaden/claude-efficient-model-selection
/plugin install efficient-model-selection@claude-efficient-model-selection
/reload-plugins
```

Works the same in Claude Code's CLI, desktop app, and IDE extensions — one plugin system across
all of them. Or non-interactively:

```sh
claude plugin marketplace add joeskolengaden/claude-efficient-model-selection
claude plugin install efficient-model-selection@claude-efficient-model-selection
```

Once installed, it loads automatically every session — nothing to invoke by name.

## Why this exists

The default instinct when delegating is to reach for the most capable model "to be safe." Most
delegated work doesn't need that: listing files, running a script and reading its output, a
focused refactor, a synthesis pass over a few sources — these have clear procedures and checkable
outcomes, and a cheaper/faster model handles them exactly as well. Defaulting to the top tier for
all of it just spends more time and cost on work that didn't need it.

Validated with three live test delegations spanning the range — a mechanical file listing (Haiku),
a bug-explanation synthesis task (Sonnet), and a ship-now-vs-keep-fixing judgment call (Opus). None
of the three needed the most expensive tier, which is the rubric working as intended, not an
undershoot.

## Updating / uninstalling

```
/plugin marketplace update claude-efficient-model-selection
/plugin uninstall efficient-model-selection@claude-efficient-model-selection
/plugin marketplace remove claude-efficient-model-selection
```

## Structure

```
.claude-plugin/marketplace.json                                              marketplace catalog
plugins/efficient-model-selection/.claude-plugin/plugin.json                 plugin manifest
plugins/efficient-model-selection/skills/efficient-model-selection/SKILL.md  the skill itself
```

Built per the official schema in [Create and distribute a plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces).

## License

MIT — see [LICENSE](LICENSE).
