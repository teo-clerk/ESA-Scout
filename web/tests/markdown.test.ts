/**
 * `lib/markdown.ts` — the browser-side half of the Markdown export.
 *
 * It is a port of `agent/exporter.py`, so these assertions deliberately mirror
 * `tests/test_exporter.py`: if the two implementations drift, one suite goes
 * red. The download naming is covered here too, since the filename is what the
 * user ends up with on disk.
 */

import { describe, expect, it } from "vitest";

import {
  allocateAnchors,
  exportFilename,
  renderOpportunities,
  renderSmeTargets,
  slugify,
} from "@/lib/markdown";
import { EMPTY_SNAPSHOT, type Snapshot } from "@/lib/types";
import { EMPTY_SME_SNAPSHOT, type Sme, type SmeSnapshot } from "@/lib/sme-types";
import {
  makeEvaluation,
  makeOpportunity,
  makeRankedSme,
  makeSme,
} from "./factories";

const EXPORT_DAY = new Date("2026-08-27T09:00:00Z");

function snapshotOf(
  opportunities: Snapshot["opportunities"],
  overrides: Partial<Snapshot> = {},
): Snapshot {
  const stats = {
    ...EMPTY_SNAPSHOT.stats,
    total: opportunities.length,
    open: opportunities.filter((o) => o.status === "Open").length,
    pending: opportunities.filter((o) => o.status === "Pending").length,
    high_fit: opportunities.filter((o) => o.match_score >= 80).length,
    evaluated: opportunities.filter((o) => o.evaluation !== null).length,
  };
  return {
    ...EMPTY_SNAPSHOT,
    generated_at: "2026-08-17T14:22:37Z",
    profile: { ...EMPTY_SNAPSHOT.profile, name: "Teo", source_file: "CV.pdf" },
    stats,
    opportunities,
    ...overrides,
  };
}

function smeSnapshotOf(
  companies: Sme[],
  overrides: Partial<SmeSnapshot> = {},
): SmeSnapshot {
  return {
    ...EMPTY_SME_SNAPSHOT,
    last_analyzed: "2026-08-23T11:42:39Z",
    countries: ["Spain", "Italy"],
    keywords: ["earth observation"],
    target_term: "Summer 2027",
    evaluated: true,
    companies,
    stats: {
      scanned: 618,
      matched: companies.length,
      evaluated: companies.filter((c) => c.evaluation !== null).length,
      strong_fit: companies.filter((c) => c.fit_score >= 70).length,
      spain: companies.filter((c) => c.country_code === "ES").length,
      italy: companies.filter((c) => c.country_code === "IT").length,
    },
    ...overrides,
  };
}

/** Score a company and keep its ranked/unranked bookkeeping consistent. */
function ranked(score: number, overrides: Partial<Sme> = {}): Sme {
  return makeRankedSme(score, overrides);
}

function headingsOf(markdown: string): string[] {
  return [...markdown.matchAll(/^### (.+)$/gm)].map((m) => m[1]);
}

function contentsLinksOf(markdown: string): string[] {
  return [...markdown.matchAll(/^ {2}- \[.+?\]\(#(.+?)\)$/gm)].map((m) => m[1]);
}

describe("slugify", () => {
  it("lower-cases and hyphenates", () => {
    expect(slugify("Navigation Training Course")).toBe("navigation-training-course");
  });

  it("drops punctuation the way GitHub does", () => {
    expect(slugify("42% — REXUS/BEXUS")).toBe("42--rexusbexus");
  });

  it("keeps accented letters", () => {
    expect(slugify("Teledetección Espacial")).toBe("teledetección-espacial");
  });

  it("gives duplicate headings distinct anchors", () => {
    expect(allocateAnchors(["Acme SL", "Acme SL", "Acme SL"])).toEqual([
      "acme-sl",
      "acme-sl-1",
      "acme-sl-2",
    ]);
  });
});

describe("renderOpportunities", () => {
  it("reports the headline metrics", () => {
    const markdown = renderOpportunities(
      snapshotOf([
        makeOpportunity({ id: "a", title: "Alpha", status: "Open", match_score: 88 }),
        makeOpportunity({ id: "b", title: "Beta", status: "Pending", match_score: 30 }),
      ]),
      80,
      EXPORT_DAY,
    );

    expect(markdown).toContain("| Open now | 1 |");
    expect(markdown).toContain("| High fit ≥ 80% | 1 |");
    expect(markdown).toContain("| Pending cycles | 1 |");
    expect(markdown).toContain("| Tracked total | 2 |");
    expect(markdown).toContain("> Exported 2026-08-27");
  });

  it("orders sections by descending fit", () => {
    const markdown = renderOpportunities(
      snapshotOf([
        makeOpportunity({ id: "a", title: "Low", match_score: 20 }),
        makeOpportunity({ id: "b", title: "High", match_score: 90 }),
      ]),
      80,
      EXPORT_DAY,
    );
    expect(headingsOf(markdown)).toEqual(["90% — High", "20% — Low"]);
  });

  it("carries fit, status, deadline and link in the summary table", () => {
    const markdown = renderOpportunities(
      snapshotOf([
        makeOpportunity({
          title: "Navigation Training Course",
          status: "Open",
          match_score: 61,
          deadline: "2026-04-05",
          url: "https://esa.example/nav",
        }),
      ]),
      80,
      EXPORT_DAY,
    );
    expect(markdown).toContain(
      "| 61% | Navigation Training Course | Open | 5 April 2026 | [Open](https://esa.example/nav) |",
    );
  });

  it("gives every contents entry an anchor that resolves to a heading", () => {
    const markdown = renderOpportunities(
      snapshotOf([
        makeOpportunity({ id: "a", title: "Acme Course", match_score: 50 }),
        makeOpportunity({ id: "b", title: "Acme Course", match_score: 50 }),
        makeOpportunity({ id: "c", title: "A/B & C: Testing", match_score: 10 }),
      ]),
      80,
      EXPORT_DAY,
    );

    const anchors = new Set(headingsOf(markdown).map(slugify));
    const links = contentsLinksOf(markdown);

    expect(links).toHaveLength(3);
    expect(new Set(links).size).toBe(3);
    for (const target of links) {
      expect(anchors.has(target) || anchors.has(target.replace(/-\d+$/, ""))).toBe(true);
    }
  });

  it("renders the full evaluation for one opportunity", () => {
    const markdown = renderOpportunities(
      snapshotOf([
        makeOpportunity({
          title: "REXUS/BEXUS",
          url: "https://esa.example/rb",
          match_score: 74,
          evaluation: makeEvaluation({
            match_score: 74,
            justification: "Strong overlap with your ML work.",
            why_apply: ["Flight hardware access"],
            required_skills: ["Python", "Proposal writing"],
            gaps: ["No aerospace coursework"],
            checklist: [
              {
                task: "Draft a concept note",
                effort: "1 week",
                done_when: "Shared with the programme office",
              },
            ],
            key_deadlines: [{ label: "Proposal due", date: "2026-10-08" }],
            model: "grok-4",
            evaluated_at: "2026-08-17T14:22:36Z",
          }),
        }),
      ]),
      80,
      EXPORT_DAY,
    );

    expect(markdown).toContain("#### AI justification");
    expect(markdown).toContain("Strong overlap with your ML work.");
    expect(markdown).toContain("- Flight hardware access");
    expect(markdown).toContain("`Python` · `Proposal writing`");
    expect(markdown).toContain("- No aerospace coursework");
    expect(markdown).toContain("- [ ] Draft a concept note");
    expect(markdown).toContain("  - Effort: 1 week");
    expect(markdown).toContain("  - Done when: Shared with the programme office");
    expect(markdown).toContain("| Proposal due | 8 October 2026 |");
    expect(markdown).toContain("_Scored by grok-4 on 2026-08-17T14:22:36Z._");
    expect(markdown).toContain("- [Opportunity page](https://esa.example/rb)");
  });

  it("marks an unevaluated opportunity instead of omitting it", () => {
    const markdown = renderOpportunities(
      snapshotOf([makeOpportunity({ title: "Unscored Thing" })]),
      80,
      EXPORT_DAY,
    );
    expect(markdown).toContain("### Unscored — Unscored Thing");
    expect(markdown).toContain("_Not evaluated yet._");
  });

  it("surfaces an evaluation error rather than pretending it scored", () => {
    const markdown = renderOpportunities(
      snapshotOf([
        makeOpportunity({
          title: "Broken",
          evaluation: makeEvaluation({ error: "LLM timed out" }),
        }),
      ]),
      80,
      EXPORT_DAY,
    );
    expect(markdown).toContain("> Evaluation failed: LLM timed out");
  });

  it("escapes a pipe in a title so the summary table survives", () => {
    const markdown = renderOpportunities(
      snapshotOf([makeOpportunity({ title: "A | B", match_score: 10 })]),
      80,
      EXPORT_DAY,
    );
    const row = markdown.split("\n").find((line) => line.startsWith("| 10%"))!;
    expect(row).toContain("A \\| B");
    // Only unescaped pipes delimit cells: 5 columns => 6 delimiters.
    expect(row.match(/(?<!\\)\|/g)).toHaveLength(6);
  });

  it("lists the run warnings", () => {
    const markdown = renderOpportunities(
      snapshotOf([makeOpportunity()], { errors: ["github: rate limited"] }),
      80,
      EXPORT_DAY,
    );
    expect(markdown).toContain("## Warnings (1)");
    expect(markdown).toContain("- github: rate limited");
  });

  it("still produces a readable document from an empty snapshot", () => {
    const markdown = renderOpportunities(EMPTY_SNAPSHOT, 80, EXPORT_DAY);
    expect(markdown.startsWith("# ESA Scout — Opportunities")).toBe(true);
    expect(markdown).toContain("_No opportunities in this snapshot._");
    expect(markdown).toContain("python -m agent.main run");
  });

  it("ends with exactly one newline", () => {
    const markdown = renderOpportunities(
      snapshotOf([makeOpportunity({ match_score: 10 })]),
      80,
      EXPORT_DAY,
    );
    expect(markdown.endsWith("\n")).toBe(true);
    expect(markdown.endsWith("\n\n")).toBe(false);
  });
});

describe("renderSmeTargets", () => {
  it("reports the overview metrics", () => {
    const markdown = renderSmeTargets(
      smeSnapshotOf([
        ranked(85, { id: "a", name: "Alpha SL" }),
        ranked(40, {
          id: "b",
          name: "Beta Srl",
          country: "Italy",
          country_code: "IT",
        }),
      ]),
      70,
      EXPORT_DAY,
    );

    expect(markdown).toContain("| Companies scanned | 618 |");
    expect(markdown).toContain("| Keyword matches | 2 |");
    expect(markdown).toContain("| Strong fit ≥ 70% | 1 |");
    expect(markdown).toContain("| Spain | 1 |");
    expect(markdown).toContain("| Italy | 1 |");
  });

  it("names the target term in the header and the rationale section", () => {
    const markdown = renderSmeTargets(smeSnapshotOf([ranked(85)]), 70, EXPORT_DAY);
    expect(markdown).toContain("**Summer 2027** internship targets");
    expect(markdown).toContain("#### Why this fits for Summer 2027");
  });

  it("carries country, city and domains in the summary table", () => {
    const markdown = renderSmeTargets(
      smeSnapshotOf([ranked(85, { name: "Acme Geospatial SL" })]),
      70,
      EXPORT_DAY,
    );
    expect(markdown).toContain(
      "| 85% | Acme Geospatial SL | ES | Madrid | Earth Observation | [Site](https://acme.example) |",
    );
  });

  it("renders domain tags, rationale and outreach advice", () => {
    const markdown = renderSmeTargets(
      smeSnapshotOf([
        makeSme({
          id: "deep-1",
          entity_id: "138796",
          name: "Deepleey Srl",
          country: "Italy",
          country_code: "IT",
          city: "Genova",
          website: "https://deepleey.example",
          description: "AI and computer vision for ESG.",
          detail_url: "https://esastar.example/138796",
          domains: ["Remote Sensing", "Computer Vision"],
          matched_keywords: ["remote sensing"],
          fit_score: 85,
          evaluation: {
            fit_score: 85,
            rationale: "Your CV work maps onto their AI stack.",
            suggested_role: "Remote sensing AI intern",
            focus_areas: ["Computer Vision"],
            outreach_tips: ["Reference their Genoa base", "Offer a mini-project"],
            model: "grok-4",
            evaluated_at: "2026-08-23T11:41:55Z",
            fingerprint: "fp",
            error: "",
          },
        }),
      ]),
      70,
      EXPORT_DAY,
    );

    expect(markdown).toContain("### 85% — Deepleey Srl");
    expect(markdown).toContain("- **Location:** Genova, Italy");
    expect(markdown).toContain("- **Website:** <https://deepleey.example>");
    expect(markdown).toContain(
      "- **ESA-star entry:** [138796](https://esastar.example/138796)",
    );
    expect(markdown).toContain(
      "- **Domain tags (inferred):** `Remote Sensing` · `Computer Vision`",
    );
    expect(markdown).toContain("AI and computer vision for ESG.");
    expect(markdown).toContain("Your CV work maps onto their AI stack.");
    expect(markdown).toContain("#### Suggested role");
    expect(markdown).toContain("- Reference their Genoa base");
    expect(markdown).toContain("_Ranked by grok-4 on 2026-08-23T11:41:55Z._");
  });

  it("says so when a company has not been ranked", () => {
    const markdown = renderSmeTargets(
      smeSnapshotOf([makeSme({ name: "Unranked SL" })]),
      70,
      EXPORT_DAY,
    );
    expect(markdown).toContain("### Unranked — Unranked SL");
    expect(markdown).toContain("_Not ranked yet._");
  });

  it("warns when the whole scan was keyword-only", () => {
    const markdown = renderSmeTargets(
      smeSnapshotOf([makeSme()], { evaluated: false }),
      70,
      EXPORT_DAY,
    );
    expect(markdown).toContain("have not been ranked yet");
    expect(markdown).toContain("`--evaluate`");
  });

  it("falls back to the ESA-star link when there is no website", () => {
    const markdown = renderSmeTargets(
      smeSnapshotOf([
        ranked(50, { website: "", detail_url: "https://esastar.example/9" }),
      ]),
      70,
      EXPORT_DAY,
    );
    expect(markdown).toContain("[ESA-star](https://esastar.example/9)");
  });

  it("states that none of these companies advertised a role", () => {
    const markdown = renderSmeTargets(smeSnapshotOf([ranked(85)]), 70, EXPORT_DAY);
    expect(markdown).toContain("cold approach");
  });

  it("still produces a readable document from an empty snapshot", () => {
    const markdown = renderSmeTargets(EMPTY_SME_SNAPSHOT, 70, EXPORT_DAY);
    expect(markdown.startsWith("# ESA Scout — SME Internship Targets")).toBe(true);
    expect(markdown).toContain("_No companies in this snapshot._");
  });
});

describe("exportFilename", () => {
  it("dates the opportunities download", () => {
    expect(exportFilename("opportunities", EXPORT_DAY)).toBe(
      "esa_opportunities_2026-08-27.md",
    );
  });

  it("dates the SME download", () => {
    expect(exportFilename("sme", EXPORT_DAY)).toBe("esa_sme_targets_2026-08-27.md");
  });
});
