"use client";

/** Search, status and category filters, plus sort order. */

import { type FilterState, isFiltered } from "@/lib/filter";
import type { SortKey, StatusFilter } from "@/lib/types";

interface Props {
  state: FilterState;
  categories: string[];
  resultCount: number;
  totalCount: number;
  onChange: (next: FilterState) => void;
}

const STATUS_OPTIONS: StatusFilter[] = ["All", "Open", "Pending", "Closed"];

const SORT_LABELS: Record<SortKey, string> = {
  match: "Match score",
  deadline: "Deadline",
  title: "Title",
};

export default function FilterBar({
  state,
  categories,
  resultCount,
  totalCount,
  onChange,
}: Props) {
  const update = (patch: Partial<FilterState>) => onChange({ ...state, ...patch });
  const showClear = isFiltered(state);

  return (
    <div className="sticky top-0 z-10 border-b border-[--color-edge] bg-[--color-void]/85 backdrop-blur">
      <div className="mx-auto max-w-7xl px-4 py-4 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
          {/* Search */}
          <div className="relative flex-1">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500"
              aria-hidden="true"
            >
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.5-3.5" />
            </svg>
            <input
              type="search"
              value={state.query}
              onChange={(e) => update({ query: e.target.value })}
              placeholder="Search titles, skills, categories…"
              aria-label="Search opportunities"
              className="w-full rounded-lg border border-[--color-edge] bg-[--color-panel] py-2 pl-9 pr-3 text-sm text-slate-200 placeholder:text-slate-600 focus:border-sky-500/50 focus:outline-none"
            />
          </div>

          {/* Status segmented control */}
          <div
            className="flex rounded-lg border border-[--color-edge] bg-[--color-panel] p-1"
            role="group"
            aria-label="Filter by status"
          >
            {STATUS_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={state.status === option}
                onClick={() => update({ status: option })}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
                  state.status === option
                    ? "bg-slate-700/70 text-slate-100"
                    : "text-slate-500 hover:text-slate-300"
                }`}
              >
                {option}
              </button>
            ))}
          </div>

          {/* Category */}
          <select
            value={state.category}
            onChange={(e) => update({ category: e.target.value })}
            aria-label="Filter by category"
            className="rounded-lg border border-[--color-edge] bg-[--color-panel] px-3 py-2 text-sm text-slate-300 focus:border-sky-500/50 focus:outline-none"
          >
            <option value="All">All categories</option>
            {categories.map((category) => (
              <option key={category} value={category}>
                {category}
              </option>
            ))}
          </select>

          {/* Sort */}
          <select
            value={state.sort}
            onChange={(e) => update({ sort: e.target.value as SortKey })}
            aria-label="Sort opportunities"
            className="rounded-lg border border-[--color-edge] bg-[--color-panel] px-3 py-2 text-sm text-slate-300 focus:border-sky-500/50 focus:outline-none"
          >
            {(Object.keys(SORT_LABELS) as SortKey[]).map((key) => (
              <option key={key} value={key}>
                Sort by {SORT_LABELS[key]}
              </option>
            ))}
          </select>
        </div>

        <div className="mt-2.5 flex items-center gap-3 text-xs text-slate-500">
          <span>
            Showing <span className="text-slate-300 tabular-nums">{resultCount}</span>{" "}
            of <span className="tabular-nums">{totalCount}</span> opportunities
          </span>
          {showClear ? (
            <button
              type="button"
              onClick={() =>
                onChange({ query: "", status: "All", category: "All", sort: state.sort })
              }
              className="text-sky-400 underline-offset-2 hover:underline"
            >
              Clear filters
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
