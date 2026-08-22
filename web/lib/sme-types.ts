/**
 * TypeScript mirror of the Python models in `agent/sme_models.py`.
 *
 * This is the on-disk contract for `data/sme_matches.json`. When you change a
 * field here, change `agent/sme_models.py` to match — the Python `to_dict`
 * methods are the source of truth.
 */

export interface SmeEvaluation {
  fit_score: number;
  rationale: string;
  suggested_role: string;
  focus_areas: string[];
  outreach_tips: string[];
  model: string;
  evaluated_at: string;
  fingerprint: string;
  error: string;
}

export interface Sme {
  id: string;
  entity_id: string;
  name: string;
  country: string;
  /** ISO-3166 alpha-2, e.g. "ES" or "IT". */
  country_code: string;
  city: string;
  website: string;
  description: string;
  entity_type: string;
  entity_size: string;
  detail_url: string;
  /**
   * Derived from the description by keyword matching — ESA-star publishes no
   * structured activity field, so the UI labels these as inferred.
   */
  domains: string[];
  matched_keywords: string[];
  content_hash: string;
  fit_score: number;
  evaluation: SmeEvaluation | null;
}

export interface SmeStats {
  scanned: number;
  matched: number;
  evaluated: number;
  strong_fit: number;
  spain: number;
  italy: number;
}

export interface SmeSnapshot {
  version: number;
  last_analyzed: string;
  countries: string[];
  keywords: string[];
  target_term: string;
  /** False when the scan ran without an LLM key (keyword-only results). */
  evaluated: boolean;
  strong_fit_threshold: number;
  stats: SmeStats;
  companies: Sme[];
  errors: string[];
}

/** Shown before the SME scan has ever run, so the page renders regardless. */
export const EMPTY_SME_SNAPSHOT: SmeSnapshot = {
  version: 1,
  last_analyzed: "",
  countries: [],
  keywords: [],
  target_term: "",
  evaluated: false,
  strong_fit_threshold: 70,
  stats: {
    scanned: 0,
    matched: 0,
    evaluated: 0,
    strong_fit: 0,
    spain: 0,
    italy: 0,
  },
  companies: [],
  errors: [],
};

export type SmeSortKey = "fit" | "name" | "domains";
export type CountryFilter = "All" | string;

/** Flag emoji for the two supported countries; "" keeps the UI text-only. */
export const COUNTRY_FLAGS: Record<string, string> = {
  ES: "🇪🇸",
  IT: "🇮🇹",
};

export function countryFlag(code: string): string {
  return COUNTRY_FLAGS[code.toUpperCase()] ?? "";
}
