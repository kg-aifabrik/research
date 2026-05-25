# Research repository

This repo holds research notes organized by area. Each subdirectory under the root is a research **area** containing one or more **topics**. Example: a `kubernetes-federation` area might contain topics on the open-source landscape, on neo-cloud deployments, etc.

## Related implementation repos

Some research areas in this repo are being actively implemented in companion repos. When a session lands here but the user's question is about *implementation* rather than research, hop over:

- **[`host-net-config/`](host-net-config/)** is being implemented in **[`kg-aifabrik/host-config`](https://github.com/kg-aifabrik/host-config)**. The [implementation plan](host-net-config/implementation-plan.md) in this repo is the durable design contract; milestone progress and code live in `host-config`. See that repo's `CLAUDE.md` for its workflow conventions (solo-dev direct-to-main, Conventional Commits, full test pyramid, the issue-closing ritual).

## Workflow

When the user asks for new research, the first thing to determine is which area folder it belongs in:

- If the prompt names an area, use it.
- If the prompt doesn't name one, **ask the user for an area folder name before doing anything else**.
- Area names are free-form. No date prefixes.

If the named area folder already exists, add new topics into it rather than creating a new one.

Before producing the full report on a new topic, **draft the Requirements and Assumptions Made sections first** (see Report structure) and present them to the user for sign-off. Wait for confirmation before doing the research and full write-up — unless the user has explicitly told you to just run with your interpretation.

## Committing

Commit after every completed unit of work in this repo without waiting to be asked, then push to `origin` on the current branch. The only exception is when the user explicitly says to hold off or wait for a follow-up prompt. Use short, specific commit messages that name what changed.

## Folder layout

```
<area>/
  README.md            # executive summary of the area
  <topic-1>.md         # report
  <topic-2>.md
  ...
```

Each topic is a single Markdown report. **Do not generate an HTML version.**

For visuals, prefer Mermaid, inline SVG, or referenced image/diagram files (Excalidraw, SVG in a `diagrams/` subfolder) embedded into the Markdown — anything that renders cleanly in a standard Markdown viewer.

## Report structure

Each topic report uses this section order:

1. **Title** — short, descriptive.
2. **Table of contents** — only when the report is long or complex enough that a reader benefits from jumping between sections. Use judgment; skip it for short reports. When present, link to the report's main sections.
3. **Executive Summary** — this is the lede. State the conclusion up front:
   - **Comparison topics:** lead with the comparison table (see *Comparisons* in Writing style) immediately followed by "Prefer X over Y because (1)…, (2)…, (3)…".
   - **Single-subject topics:** lead with the headline finding (e.g. "Service X handles N requests/sec by way of A, B, C").
   A reader who stops here should already have the takeaway.
4. **Requirements** — bullet list of all requirements as understood for this research. Should have been confirmed with the user before the report was written.
5. **Assumptions Made** — bullet list of every explicit assumption you made. Should also have been confirmed with the user beforehand; flag any that weren't.
6. **Report body** — supporting detail in decreasing order of importance.

## Writing style

Reports are written for a reader proficient in the topic. Optimize for their time and attention, not for completeness.

- **Inverted pyramid.** The Executive Summary (see Report structure) carries the essence — it is the lede. The report body layers supporting detail below in decreasing order of importance.
- **Terse.** No throat-clearing, no restating the question, no "in conclusion." Cut adjectives. Prefer concrete numbers, named systems, and specific claims over abstractions.
- **Acronyms.** On first occurrence, expand the term — e.g. "Kubernetes (K8s)", "Container Network Interface (CNI)". Subsequent uses can be the acronym alone. Applies per report, not per session.
- **Length budget.** Keep each report under 4 printed pages. If a topic genuinely cannot fit, produce the long version and **ask the user which sections to trim** before finalizing.
- **Citations.** Important — cite primary sources where possible. Use inline Markdown links embedded in the prose: `[phrase](url)`. No trailing reference list — keep the link details out of the reading flow.
- **Visuals.** Mermaid diagrams, inline SVG, KaTeX, comparison tables, etc. are all fair game when they convey more than prose would. Pick the right tool for the topic.
- **Comparisons.** When the report compares options, the Executive Summary leads with a table:
  - **Columns = the choices** being compared (A, B, C…).
  - **Rows = the dimensions** of comparison (cost, latency, operational burden, etc.).
  - Immediately below the table, state the **conclusion** — "Prefer A over B because (1)…, (2)…, (3)…".
  - Per-dimension caveats and deeper analysis live in the report body, not the Exec Summary.
- **Style.** No fixed template — choose typography and layout that suit the content. A landscape comparison will look different from a deep-dive on one protocol.

## Area README

Each area's `README.md` is an **executive summary**, not a table of contents:

- **5–7 bullets** that convey the essence of what the area covers and the current state of research.
- Include **open threads / unanswered questions** so a future session can pick up where this one stopped.
- Refresh the README when findings or conclusions in the area meaningfully change. Use judgment — a typo fix or wording tweak does not warrant a refresh; a new topic, a revised conclusion, or a newly surfaced open question does.

## Root index

The repo-level `README.md` is the index of areas. Keep it in sync:

- One line per area: `- [area-name](area-name/) — one-sentence summary.`
- Add an entry when a new area folder is created.
- Update an entry's summary when the area's scope materially shifts.
- Remove an entry if an area is deleted.
