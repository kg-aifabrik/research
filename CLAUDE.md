# Research repository

This repo holds research notes organized by area. Each subdirectory under the root is a research **area** containing one or more **topics**. Example: a `kubernetes-federation` area might contain topics on the open-source landscape, on neo-cloud deployments, etc.

## Workflow

When the user asks for new research, the first thing to determine is which area folder it belongs in:

- If the prompt names an area, use it.
- If the prompt doesn't name one, **ask the user for an area folder name before doing anything else**.
- Area names are free-form. No date prefixes.

If the named area folder already exists, add new topics into it rather than creating a new one.

## Committing

Commit after every completed unit of work in this repo without waiting to be asked. The only exception is when the user explicitly says to hold off or wait for a follow-up prompt. Use short, specific commit messages that name what changed.

## Folder layout

```
<area>/
  README.md            # executive summary of the area
  <topic-1>.md         # report
  <topic-1>.html       # self-contained HTML version of the same report
  <topic-2>.md
  <topic-2>.html
  ...
```

Each topic produces a paired `.md` and `.html` with matching base names. Both files must convey the same content. The HTML is for browser review and must be **fully self-contained** — inline CSS, no external JS, no external font or image fetches. The only external references allowed are citation links in the prose.

## Writing style

Reports are written for a reader proficient in the topic. Optimize for their time and attention, not for completeness.

- **Inverted pyramid.** Open with a one-line headline and a lede paragraph that delivers the essence. A reader who stops after the lede should already have the takeaway. Layer supporting detail below in decreasing order of importance.
- **Terse.** No throat-clearing, no restating the question, no "in conclusion." Cut adjectives. Prefer concrete numbers, named systems, and specific claims over abstractions.
- **Acronyms.** On first occurrence, expand the term — e.g. "Kubernetes (K8s)", "Container Network Interface (CNI)". Subsequent uses can be the acronym alone. Applies per report, not per session.
- **Length budget.** Keep each report under 4 printed pages. If a topic genuinely cannot fit, produce the long version and **ask the user which sections to trim** before finalizing.
- **Citations.** Important — cite primary sources where possible. Use inline anchor links embedded in the prose: `<a href="...">phrase</a>` in HTML, `[phrase](url)` in Markdown. No trailing reference list — keep the link details out of the reading flow.
- **Visuals.** Mermaid diagrams, inline SVG, KaTeX, comparison tables, etc. are all fair game when they convey more than prose would. Pick the right tool for the topic.
- **Comparisons.** When the report compares options, lead with a table:
  - **Columns = the choices** being compared (A, B, C…).
  - **Rows = the dimensions** of comparison (cost, latency, operational burden, etc.).
  - Immediately below the table, state the **conclusion** — "Prefer A over B because (1)…, (2)…, (3)…" — before any deeper analysis.
  - Per-dimension detail and caveats follow below the conclusion, not above it.
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
