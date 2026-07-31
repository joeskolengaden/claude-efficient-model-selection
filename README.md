# claude-efficient-model-selection

A Claude Code plugin marketplace with one plugin: **efficient-model-selection** — standing
guidance for picking the cheapest model tier (Haiku/Sonnet/Opus/Fable) that reliably handles a
delegated task, instead of defaulting to the most capable one for everything.

It applies whenever you're about to hand work to a subagent (the `Agent` tool), author an
`agent()` call inside a `Workflow` script, or plan a multi-step task whose pieces differ in
difficulty. It does **not** change the main conversation's own model — that stays under your
control via `/model`.

See [`plugins/efficient-model-selection/skills/efficient-model-selection/SKILL.md`](plugins/efficient-model-selection/skills/efficient-model-selection/SKILL.md)
for the full guidance.

## Install

In Claude Code (CLI, desktop app, or IDE extension — same plugin system across all of them):

```
/plugin marketplace add joeskolengaden/claude-efficient-model-selection
/plugin install efficient-model-selection@claude-efficient-model-selection
/reload-plugins
```

Or non-interactively:

```sh
claude plugin marketplace add joeskolengaden/claude-efficient-model-selection
claude plugin install efficient-model-selection@claude-efficient-model-selection
```

Once installed, the skill loads automatically in every session — no need to invoke it by name.

## Updating

```
/plugin marketplace update claude-efficient-model-selection
```

## Uninstall

```
/plugin uninstall efficient-model-selection@claude-efficient-model-selection
/plugin marketplace remove claude-efficient-model-selection
```

## Structure

```
.claude-plugin/marketplace.json                                   marketplace catalog
plugins/efficient-model-selection/.claude-plugin/plugin.json       plugin manifest
plugins/efficient-model-selection/skills/efficient-model-selection/SKILL.md   the skill itself
```

Built per the official schema in [Create and distribute a plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces).
