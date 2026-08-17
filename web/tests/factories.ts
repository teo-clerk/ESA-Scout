import type { Evaluation, Opportunity, Status } from "@/lib/types";

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
