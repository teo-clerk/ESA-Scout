import type { Evaluation, Opportunity, Status } from "@/lib/types";
import type { Sme, SmeEvaluation } from "@/lib/sme-types";

export function makeEvaluation(overrides: Partial<Evaluation> = {}): Evaluation {
  return {
    match_score: 0,
    justification: "",
    why_apply: [],
    required_skills: [],
    gaps: [],
    checklist: [],
    key_deadlines: [],
    model: "test-model",
    evaluated_at: "2026-08-17T00:00:00Z",
    fingerprint: "fp",
    error: "",
    ...overrides,
  };
}

export function makeOpportunity(
  overrides: Partial<Opportunity> = {},
): Opportunity {
  const status: Status = overrides.status ?? "Open";
  return {
    id: "esa-tlp-test",
    title: "Test Training Course",
    source: "esa_tlp",
    source_label: "ESA Academy TLP",
    url: "https://example.esa.int/opportunity",
    status,
    kind: "Training Course",
    category: "Space Systems",
    location: "",
    summary: "",
    activity_dates: "",
    activity_start: "",
    deadline_text: "",
    deadline: "2026-12-01",
    first_seen: "",
    last_seen: "",
    content_hash: "abc123",
    match_score: 0,
    evaluation: null,
    ...overrides,
  };
}

// --- SME factories ---------------------------------------------------------

export function makeSmeEvaluation(
  overrides: Partial<SmeEvaluation> = {},
): SmeEvaluation {
  return {
    fit_score: 0,
    rationale: "",
    suggested_role: "",
    focus_areas: [],
    outreach_tips: [],
    model: "test-model",
    evaluated_at: "2026-08-22T00:00:00Z",
    fingerprint: "fp",
    error: "",
    ...overrides,
  };
}

export function makeSme(overrides: Partial<Sme> = {}): Sme {
  const evaluation = overrides.evaluation ?? null;
  return {
    id: "acme-1",
    entity_id: "1",
    name: "Acme Geospatial SL",
    country: "Spain",
    country_code: "ES",
    city: "Madrid",
    website: "https://acme.example",
    description: "We process Sentinel-2 imagery.",
    entity_type: "Company",
    entity_size: "Small",
    detail_url: "https://esastar-emr.sso.esa.int/PublicEntityDir/x/1",
    domains: ["Earth Observation"],
    matched_keywords: ["earth observation"],
    content_hash: "hash",
    fit_score: evaluation?.fit_score ?? 0,
    ...overrides,
    evaluation,
  };
}

/** A ranked company: keeps `fit_score` and the evaluation consistent. */
export function makeRankedSme(score: number, overrides: Partial<Sme> = {}): Sme {
  return makeSme({
    ...overrides,
    fit_score: score,
    evaluation: makeSmeEvaluation({
      fit_score: score,
      rationale: "Two sentences. Here they are.",
      ...(overrides.evaluation ?? {}),
    }),
  });
}
