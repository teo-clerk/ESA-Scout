/**
 * Pure filtering and sorting for the opportunity list.
 *
 * Deliberately free of React so the behaviour can be unit-tested directly —
 * this is where ordering and search bugs would otherwise hide.
 */

import type { Opportunity, SortKey, StatusFilter } from "./types";

export interface FilterState {
  query: string;
  status: StatusFilter;
  category: string;
  sort: SortKey;
}

export const INITIAL_FILTERS: FilterState = {
  query: "",
  status: "All",
  category: "All",
  sort: "match",
};

/** Sorts undated entries last instead of first in an ascending comparison. */
const NO_DEADLINE = "9999-12-31";

export function isFiltered(state: FilterState): boolean {
  return state.query !== "" || state.status !== "All" || state.category !== "All";
}

/** Everything the search box should match against, lower-cased. */
function searchableText(opportunity: Opportunity): string {
  return [
    opportunity.title,
    opportunity.category,
    opportunity.kind,
    opportunity.location,
    opportunity.summary,
    opportunity.source_label,
    // AI-derived fields too, so "python" finds courses that require it.
    ...(opportunity.evaluation?.required_skills ?? []),
    ...(opportunity.evaluation?.why_apply ?? []),
  ]
    .join(" ")
    .toLowerCase();
}

export function applyFilters(
  opportunities: Opportunity[],
  filters: FilterState,
): Opportunity[] {
  const query = filters.query.trim().toLowerCase();

  const filtered = opportunities.filter((opportunity) => {
    if (filters.status !== "All" && opportunity.status !== filters.status) {
      return false;
    }
    if (filters.category !== "All" && opportunity.category !== filters.category) {
      return false;
    }
    return query ? searchableText(opportunity).includes(query) : true;
  });

  return sortOpportunities(filtered, filters.sort);
}

export function sortOpportunities(
  opportunities: Opportunity[],
  sort: SortKey,
): Opportunity[] {
  // Copy before sorting: never mutate an array handed down through props.
  const copy = [...opportunities];

  switch (sort) {
    case "deadline":
      return copy.sort((a, b) =>
        (a.deadline || NO_DEADLINE).localeCompare(b.deadline || NO_DEADLINE),
      );
    case "title":
      return copy.sort((a, b) => a.title.localeCompare(b.title));
    case "match":
    default:
      return copy.sort(
        (a, b) =>
          b.match_score - a.match_score ||
          (a.deadline || NO_DEADLINE).localeCompare(b.deadline || NO_DEADLINE),
      );
  }
}
