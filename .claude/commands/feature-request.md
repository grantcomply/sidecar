---
description: Plan a new feature — architect blueprint + UI design brief, saved to plans/
argument-hint: <feature description>
allowed-tools: Agent, Read, Glob, Grep, Bash, Write, Edit
---

# Feature request workflow

The user is requesting a new feature. Take them through the standard Serato Sidecar
planning pipeline:

1. **architect** agent produces the architecture blueprint + implementation plan.
2. **ui-designer** agent reviews the UI implications, produces a design brief, and
   revises the architect's plan with UI-driven changes.
3. Final artefacts land in `plans/<feature-slug>-<YYYY-MM>/`.

This command is **planning only**. Implementation happens afterwards via the normal
architect → engineer → code-reviewer workflow in `CLAUDE.md`.

## User's feature description

$ARGUMENTS

## How to run this

### Step 0 — sanity-check the request

If `$ARGUMENTS` is empty or so vague the architect can't reason about it (e.g. "add a
thing"), stop and ask the user for: the user-facing problem, who it helps (the DJ
mid-set, or the user configuring the app), and roughly what they expect to see. Do
**not** invent a feature.

If the description is workable, restate it back in one sentence so the user can correct
course before two agents spend time on it. Then proceed without waiting for
confirmation (auto mode is the norm here).

### Step 1 — pick a folder

Derive a kebab-case slug from the feature (e.g. `crate-color-filter`, not
`crate color filter`). Append the current year-month from the system date — e.g.
`crate-color-filter-2026-05`. The folder is `plans/<slug>-<YYYY-MM>/`.

If the folder already exists, append `-v2` (or the next free suffix) rather than
overwriting.

Create the folder. Don't pre-write empty files — the agents do that.

### Step 2 — architect agent (foreground)

Spawn the **architect** agent with a self-contained brief. The agent has
Read/Grep/Glob/Write/Edit and should write its output directly into the plan folder,
not return prose for you to save.

Required deliverables (two files):

- `<folder>/architect-blueprint.md` — Context, Decision, Affected files, Phases,
  Risks & open questions. ADR-style if a cross-cutting decision is involved; otherwise
  a feature blueprint.
- `<folder>/implementation-plan.md` — ordered tasks with `file:line` citations for
  where each change lands, broken into phases the engineer can execute one at a time.

Pass the architect:

- The full feature description verbatim.
- The folder path it should write into.
- A reminder to read `CLAUDE.md`, `docs/architecture-overview.md`,
  `docs/architecture-decisions.md`, `docs/coding-standards.md`, and
  `docs/cross-platform-guide.md` before reasoning, and to cite `file:line`.
- A reminder to check the "Architectural Debt" list in `docs/architecture-overview.md`
  and existing ADRs in `docs/architecture-decisions.md` where they constrain the design.
- A note that this feature **may or may not** have UI surface. If it does, the
  ui-designer will review and may request changes — leave UI-shaped sections explicitly
  marked `<!-- UI-designer to revise -->` so they're easy to find.

Wait for the architect to finish.

### Step 3 — UI designer agent (foreground)

If the architect blueprint indicates **no UI surface** (pure backend / data / parsing
work with no panel, dialog, or visible change), skip this step and tell the user UI
review was skipped because the feature has no UI.

Otherwise spawn the **ui-designer** agent with a self-contained brief. It has
Read/Grep/Glob/Write/Edit.

Required deliverables:

- `<folder>/ui-design-brief.md` — using the design-brief format from
  `.claude/agents/ui-designer.md` (User goal; Panels/components affected; Pattern
  precedent with `file:line`; States to handle; Microcopy; Open questions; Risks).
- **Revisions to `architect-blueprint.md` and/or `implementation-plan.md`** — the
  ui-designer edits the architect's docs in-place to replace the
  `<!-- UI-designer to revise -->` placeholders with concrete UI direction, and
  adds/removes tasks where UI work was missing or wrongly scoped. It must leave a short
  `## UI revisions applied` section at the bottom of `implementation-plan.md`
  summarising what it changed and why.

Pass the ui-designer:

- The feature description.
- The folder path containing the architect's two files.
- **Explicit permission to edit the architect's files** (the agent is sometimes
  cautious about this).
- A reminder to read `docs/ui-design-guide.md` first and cite `file:line` for pattern
  precedents.

Wait for the ui-designer to finish.

### Step 4 — report back

End with a short summary to the user:

- The folder path.
- The files produced (architect blueprint, implementation plan, UI design brief — or
  note that UI review was skipped).
- The top 1–3 open questions the user must answer before implementation can start,
  drawn from the agents' "Open questions" sections.
- A one-line next step — typically: "Reply with answers to the open questions, or say
  'proceed' and I'll hand phase 1 of the implementation plan to the engineer."

Do **not** start implementing the feature in this command. Planning only.

## Guardrails

- **Don't commit anything.** The user handles all git operations.
- **Don't write the plan content yourself.** The agents own that. Your job is
  orchestration: pick the folder, brief the agents, surface the result.
- If the architect or ui-designer produces output that conflicts with an existing ADR
  in `docs/architecture-decisions.md` or with `docs/ui-design-guide.md`, flag the
  conflict explicitly in the report-back rather than letting it ship silently into a
  plan doc.
- Both agents run in the **foreground, sequentially** — architect first, then
  ui-designer (which depends on the architect's output). Do not parallelise them.
