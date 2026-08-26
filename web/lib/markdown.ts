/**
 * Markdown rendering for the two snapshots, mirroring `agent/exporter.py`.
 *
 * The CLI writes `OPPORTUNITIES.md` / `SME_TARGETS.md` from Python; the
 * dashboard's "Export .md" button has to produce the same documents without a
 * Python runtime, because Vercel only ships the Next.js app. This module is a
 * direct port — headings, table columns and anchor slugs match line for line.
 * Change one, change the other.
 */

import { formatDate } from "./format";
import type { ChecklistItem, KeyDeadline, Opportunity, Snapshot } from "./types";
import type { Sme, SmeSnapshot } from "./sme-types";

/** Long prose is clipped in summary tables; the full text is in the section. */
const CELL_LIMIT = 90;

export type ExportType = "opportunities" | "sme";

// --- Markdown primitives ---------------------------------------------------

// GitHub builds a heading anchor by lower-casing, dropping punctuation and
// turning spaces into hyphens. Reproduced so the contents links resolve.
const SLUG_DROP = /[^\p{L}\p{N}\p{M}_\- ]/gu;
const WHITESPACE = /\s+/g;

/** GitHub-compatible heading anchor for `text`. */
export function slugify(text: string): string {
  return text
    .replace(WHITESPACE, " ")
    .trim()
    .toLowerCase()
    .replace(SLUG_DROP, "")
    .replace(/ /g, "-");
}

/** Hands out unique anchors, suffixing duplicates the way GitHub does. */
export function allocateAnchors(headings: string[]): string[] {
  const seen = new Map<string, number>();
  return headings.map((heading) => {
    const base = slugify(heading);
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    return count === 0 ? base : `${base}-${count}`;
  });
}

/** Collapse a value to a single line so it cannot break a table row. */
function inline(text: string | null | undefined): string {
  return String(text ?? "").replace(WHITESPACE, " ").trim();
}

/** Escape a value for use inside a Markdown table cell. */
function cell(text: string, limit = 0): string {
  let value = inline(text).replace(/\|/g, "\\|");
  if (limit && value.length > limit) {
    value = `${value.slice(0, limit - 1).trimEnd()}…`;
  }
  return value || "—";
}

type Align = "left" | "right" | "center";
const RULES: Record<Align, string> = {
  left: "---",
  right: "---:",
  center: ":---:",
};

function table(
  headers: string[],
  aligns: Align[],
  rows: string[][],
): string[] {
  return [
    `| ${headers.join(" | ")} |`,
    `| ${aligns.map((a) => RULES[a]).join(" | ")} |`,
    ...rows.map((row) => `| ${row.join(" | ")} |`),
  ];
}

function bullets(items: string[]): string[] {
  return items.map(inline).filter(Boolean).map((item) => `- ${item}`);
}

/** Inline code chips, e.g. `Python` · `OpenCV`. */
function tags(values: string[]): string {
  const kept = values.map(inline).filter(Boolean);
  return kept.length ? kept.map((v) => `\`${v}\``).join(" · ") : "—";
}

/** A Markdown link, or the bare label when there is no URL. */
function link(label: string, url: string): string {
  const text = inline(label) || "link";
  return url ? `[${text}](${inline(url)})` : text;
}

/** Append `heading` plus `body` only when there is something to show. */
function section(lines: string[], heading: string, body: string[]): void {
  if (!body.length) return;
  lines.push("", heading, "", ...body);
}

/** Score for a table cell; an em dash keeps unscored columns aligned. */
function score(value: number): string {
  return value ? `${value}%` : "—";
}

/** Score for a heading, where a bare dash would read as a missing title. */
function rankLabel(value: number, absent: string): string {
  return value ? `${value}%` : absent;
}

/** Facts list, skipping every entry with nothing to say. */
function facts(entries: [string, string][]): string[] {
  return entries
    .filter(([, value]) => inline(value))
    .map(([label, value]) => `- **${label}:** ${inline(value)}`);
}

/** A trailing section listing the warnings the run recorded. */
function warnings(errors: string[]): string[] {
  if (!errors.length) return [];
  return ["", `## Warnings (${errors.length})`, "", ...bullets(errors)];
}

/** YYYY-MM-DD in UTC, matching the CLI's export stamp. */
export function isoDay(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10);
}

function document(lines: string[]): string {
  return `${lines.join("\n").replace(/\s+$/, "")}\n`;
}

// --- Opportunities ---------------------------------------------------------

/** Render the opportunities snapshot as a standalone Markdown document. */
export function renderOpportunities(
  snapshot: Snapshot,
  highFitThreshold = 80,
  generatedOn: Date = new Date(),
): string {
  const items = [...snapshot.opportunities].sort(
    (a, b) =>
      b.match_score - a.match_score ||
      a.title.toLowerCase().localeCompare(b.title.toLowerCase()),
  );
  const headings = items.map(
    (o) => `${rankLabel(o.match_score, "Unscored")} — ${inline(o.title)}`,
  );
  const slugs = allocateAnchors(headings);
  const stats = snapshot.stats;

  const lines: string[] = [
    "# ESA Scout — Opportunities",
    "",
    `> Exported ${isoDay(generatedOn)} · data collected ${
      inline(snapshot.generated_at) || "never"
    }.`,
  ];
  if (snapshot.profile.name) {
    lines.push(
      `> Scored against **${inline(snapshot.profile.name)}**${profileSuffix(snapshot)}.`,
    );
  }

  lines.push("", "## At a glance", "");
  lines.push(
    ...table(
      ["Metric", "Count"],
      ["left", "right"],
      [
        ["Open now", String(stats.open)],
        [`High fit ≥ ${highFitThreshold}%`, String(stats.high_fit)],
        ["Pending cycles", String(stats.pending)],
        ["Closed", String(stats.closed)],
        ["AI-evaluated", String(stats.evaluated)],
        ["Tracked total", String(stats.total)],
      ],
    ),
  );

  lines.push("", "## Contents", "");
  if (items.length) {
    lines.push("- [Summary](#summary)", "- [Opportunities](#opportunities)");
    lines.push(...headings.map((h, i) => `  - [${h}](#${slugs[i]})`));
  } else {
    lines.push("- Nothing tracked yet — run `python -m agent.main run`.");
  }

  lines.push("", "## Summary", "");
  lines.push(
    ...(items.length
      ? table(
          ["Fit", "Title", "Status", "Deadline", "Link"],
          ["right", "left", "left", "left", "left"],
          items.map((o) => [
            score(o.match_score),
            cell(o.title, CELL_LIMIT),
            cell(o.status),
            cell(formatDate(o.deadline, o.deadline_text), CELL_LIMIT),
            o.url ? link("Open", o.url) : "—",
          ]),
        )
      : ["_No opportunities in this snapshot._"]),
  );

  if (items.length) {
    lines.push("", "## Opportunities");
    headings.forEach((heading, index) => {
      lines.push("", `### ${heading}`);
      lines.push(...opportunityBody(items[index]));
      lines.push("", "---");
    });
  }

  lines.push(...warnings(snapshot.errors));
  return document(lines);
}

function profileSuffix(snapshot: Snapshot): string {
  const github = snapshot.profile.github.username;
  const parts = [
    snapshot.profile.source_file,
    github ? `GitHub @${github}` : "",
  ].filter(Boolean);
  return parts.length ? ` (${parts.join(" + ")})` : "";
}

/** The facts, AI assessment and checklist for one opportunity. */
function opportunityBody(opportunity: Opportunity): string[] {
  const lines = [
    "",
    ...facts([
      ["Status", opportunity.status],
      ["Fit score", opportunity.match_score ? `${opportunity.match_score}%` : ""],
      ["Source", opportunity.source_label || opportunity.source],
      ["Category", opportunity.category],
      ["Kind", opportunity.kind],
      ["Location", opportunity.location],
      ["Activity dates", opportunity.activity_dates],
      ["Deadline", formatDate(opportunity.deadline, opportunity.deadline_text)],
      ["First seen", opportunity.first_seen],
      ["Last seen", opportunity.last_seen],
    ]),
  ];

  if (opportunity.summary) lines.push("", inline(opportunity.summary));

  const evaluation = opportunity.evaluation;
  if (!evaluation) {
    lines.push("", "_Not evaluated yet._");
  } else if (evaluation.error) {
    lines.push("", `> Evaluation failed: ${inline(evaluation.error)}`);
  } else {
    section(
      lines,
      "#### AI justification",
      evaluation.justification ? [inline(evaluation.justification)] : [],
    );
    section(lines, "#### Why apply", bullets(evaluation.why_apply));
    section(
      lines,
      "#### Required skills",
      evaluation.required_skills.length ? [tags(evaluation.required_skills)] : [],
    );
    section(lines, "#### Gaps to close", bullets(evaluation.gaps));
    section(lines, "#### Preparation checklist", checklist(evaluation.checklist));
    section(lines, "#### Key deadlines", keyDeadlines(evaluation.key_deadlines));
    if (evaluation.model) {
      lines.push("", `_Scored by ${inline(evaluation.model)}${scoredOn(evaluation.evaluated_at)}._`);
    }
  }

  section(
    lines,
    "#### Links",
    opportunity.url ? [`- ${link("Opportunity page", opportunity.url)}`] : [],
  );
  return lines;
}

function scoredOn(evaluatedAt: string): string {
  return evaluatedAt ? ` on ${inline(evaluatedAt)}` : "";
}

/** Checklist entries as GitHub task-list items with their metadata. */
function checklist(items: ChecklistItem[]): string[] {
  const lines: string[] = [];
  for (const item of items) {
    const task = inline(item.task);
    if (!task) continue;
    lines.push(`- [ ] ${task}`);
    if (item.effort) lines.push(`  - Effort: ${inline(item.effort)}`);
    if (item.done_when) lines.push(`  - Done when: ${inline(item.done_when)}`);
  }
  return lines;
}

function keyDeadlines(items: KeyDeadline[]): string[] {
  const rows = items
    .filter((item) => inline(item.label))
    .map((item) => [cell(item.label), cell(formatDate(item.date, item.date))]);
  return rows.length ? table(["Milestone", "Date"], ["left", "left"], rows) : [];
}

// --- SME targets -----------------------------------------------------------

/** Render the SME snapshot as a standalone Markdown document. */
export function renderSmeTargets(
  snapshot: SmeSnapshot,
  strongFitThreshold = snapshot.strong_fit_threshold || 70,
  generatedOn: Date = new Date(),
): string {
  const items = [...snapshot.companies].sort(
    (a, b) =>
      b.fit_score - a.fit_score ||
      a.name.toLowerCase().localeCompare(b.name.toLowerCase()),
  );
  const headings = items.map(
    (c) => `${rankLabel(c.fit_score, "Unranked")} — ${inline(c.name)}`,
  );
  const slugs = allocateAnchors(headings);
  const stats = snapshot.stats;

  const term = inline(snapshot.target_term) || "the target term";
  const countries = snapshot.countries.join(" and ") || "the configured countries";

  const lines: string[] = [
    "# ESA Scout — SME Internship Targets",
    "",
    `> Exported ${isoDay(generatedOn)} · directory analysed ${
      inline(snapshot.last_analyzed) || "never"
    }.`,
    `> ESA-registered SMEs in ${countries}, ranked as speculative **${term}** internship targets.`,
    "",
    "None of these companies has advertised an internship — treat every one as a cold approach.",
    "",
    "## At a glance",
    "",
    ...table(
      ["Metric", "Count"],
      ["left", "right"],
      [
        ["Companies scanned", String(stats.scanned)],
        ["Keyword matches", String(stats.matched)],
        ["AI-ranked", String(stats.evaluated)],
        [`Strong fit ≥ ${strongFitThreshold}%`, String(stats.strong_fit)],
        ["Spain", String(stats.spain)],
        ["Italy", String(stats.italy)],
      ],
    ),
  ];

  if (snapshot.keywords.length) {
    lines.push("", `**Keyword filter:** ${tags(snapshot.keywords)}`);
  }
  if (!snapshot.evaluated && snapshot.companies.length) {
    lines.push(
      "",
      "> These companies matched the keyword filter but have not been ranked yet. " +
        "Re-run with `--evaluate` once `LLM_API_KEY` is set.",
    );
  }

  lines.push("", "## Contents", "");
  if (items.length) {
    lines.push("- [Summary](#summary)", "- [Companies](#companies)");
    lines.push(...headings.map((h, i) => `  - [${h}](#${slugs[i]})`));
  } else {
    lines.push("- Nothing matched yet — run `python -m agent.main sme --evaluate`.");
  }

  lines.push("", "## Summary", "");
  lines.push(
    ...(items.length
      ? table(
          ["Fit", "Company", "Country", "City", "Domains", "Link"],
          ["right", "left", "left", "left", "left", "left"],
          items.map((c) => [
            score(c.fit_score),
            cell(c.name, CELL_LIMIT),
            cell(c.country_code || c.country),
            cell(c.city),
            cell(c.domains.join(", "), CELL_LIMIT),
            c.website ? link("Site", c.website) : link("ESA-star", c.detail_url),
          ]),
        )
      : ["_No companies in this snapshot._"]),
  );

  if (items.length) {
    lines.push("", "## Companies");
    headings.forEach((heading, index) => {
      lines.push("", `### ${heading}`);
      lines.push(...smeBody(items[index], term));
      lines.push("", "---");
    });
  }

  lines.push(...warnings(snapshot.errors));
  return document(lines);
}

/** The facts, inferred domains and outreach advice for one company. */
function smeBody(company: Sme, term: string): string[] {
  const location = [company.city, company.country].filter(Boolean).join(", ");
  const lines = [
    "",
    ...facts([
      ["Fit score", company.fit_score ? `${company.fit_score}%` : ""],
      ["Location", location],
      ["Entity type", company.entity_type],
      ["Entity size", company.entity_size],
      ["Website", company.website ? `<${company.website}>` : ""],
      [
        "ESA-star entry",
        company.detail_url ? link(company.entity_id || "detail", company.detail_url) : "",
      ],
    ]),
  ];

  if (company.domains.length) {
    lines.push(`- **Domain tags (inferred):** ${tags(company.domains)}`);
  }
  if (company.matched_keywords.length) {
    lines.push(`- **Matched keywords:** ${tags(company.matched_keywords)}`);
  }
  if (company.description) lines.push("", inline(company.description));

  const evaluation = company.evaluation;
  if (!evaluation) {
    lines.push("", "_Not ranked yet._");
  } else if (evaluation.error) {
    lines.push("", `> Ranking failed: ${inline(evaluation.error)}`);
  } else {
    section(
      lines,
      `#### Why this fits for ${term}`,
      evaluation.rationale ? [inline(evaluation.rationale)] : [],
    );
    section(
      lines,
      "#### Suggested role",
      evaluation.suggested_role ? [inline(evaluation.suggested_role)] : [],
    );
    section(
      lines,
      "#### Focus areas",
      evaluation.focus_areas.length ? [tags(evaluation.focus_areas)] : [],
    );
    section(lines, "#### Outreach advice", bullets(evaluation.outreach_tips));
    if (evaluation.model) {
      lines.push("", `_Ranked by ${inline(evaluation.model)}${scoredOn(evaluation.evaluated_at)}._`);
    }
  }
  return lines;
}

// --- Download naming -------------------------------------------------------

/** `esa_opportunities_2026-08-27.md` — the name the browser saves as. */
export function exportFilename(type: ExportType, now: Date = new Date()): string {
  const stem = type === "sme" ? "esa_sme_targets" : "esa_opportunities";
  return `${stem}_${isoDay(now)}.md`;
}
