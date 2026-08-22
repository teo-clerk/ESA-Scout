/**
 * Pure filtering and sorting for the SME target list.
 *
 * Kept free of React so the behaviour is unit-testable — with ~300 companies
 * this is where a subtle ordering or matching bug would hide.
 */

import type { CountryFilter, Sme, SmeSortKey } from "./sme-types";

export interface SmeFilterState {
  query: string;
  country: CountryFilter;
  domain: string;
  /** Hide companies the AI has not ranked yet (the budget leaves some out). */
  rankedOnly: boolean;
  sort: SmeSortKey;
}

export const INITIAL_SME_FILTERS: SmeFilterState = {
  query: "",
  country: "All",
  domain: "All",
  rankedOnly: false,
  sort: "fit",
};

export function isSmeFiltered(state: SmeFilterState): boolean {
  return (
    state.query !== "" ||
    state.country !== "All" ||
    state.domain !== "All" ||
    state.rankedOnly
  );
}

/** Everything the search box should match against, lower-cased. */
function searchableText(company: Sme): string {
  return [
    company.name,
    company.city,
    company.country,
    company.description,
    ...company.domains,
    company.evaluation?.suggested_role ?? "",
    ...(company.evaluation?.focus_areas ?? []),
  ]
    .join(" ")
    .toLowerCase();
}

export function isRanked(company: Sme): boolean {
  return company.evaluation !== null && !company.evaluation.error;
}

export function applySmeFilters(
  companies: Sme[],
  filters: SmeFilterState,
): Sme[] {
  const query = filters.query.trim().toLowerCase();

  const filtered = companies.filter((company) => {
    if (filters.country !== "All" && company.country_code !== filters.country) {
      return false;
    }
    if (filters.domain !== "All" && !company.domains.includes(filters.domain)) {
      return false;
    }
    if (filters.rankedOnly && !isRanked(company)) {
      return false;
    }
    return query ? searchableText(company).includes(query) : true;
  });

  return sortSmes(filtered, filters.sort);
}

export function sortSmes(companies: Sme[], sort: SmeSortKey): Sme[] {
  // Copy before sorting: never mutate an array handed down through props.
  const copy = [...companies];

  switch (sort) {
    case "name":
      return copy.sort((a, b) => a.name.localeCompare(b.name));
    case "domains":
      return copy.sort(
        (a, b) =>
          b.domains.length - a.domains.length ||
          b.fit_score - a.fit_score ||
          a.name.localeCompare(b.name),
      );
    case "fit":
    default:
      return copy.sort(
        (a, b) => b.fit_score - a.fit_score || a.name.localeCompare(b.name),
      );
  }
}

/** Every derived domain present in the data, alphabetically. */
export function domainsOf(companies: Sme[]): string[] {
  const seen = new Set<string>();
  for (const company of companies) {
    for (const domain of company.domains) seen.add(domain);
  }
  return [...seen].sort((a, b) => a.localeCompare(b));
}

/** Country codes present in the data, in the order the agent scanned them. */
export function countriesOf(companies: Sme[]): string[] {
  const seen: string[] = [];
  for (const company of companies) {
    if (company.country_code && !seen.includes(company.country_code)) {
      seen.push(company.country_code);
    }
  }
  return seen;
}
