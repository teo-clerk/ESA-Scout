"use client";

/**
 * Client shell: owns filter/sort state and composes the header, filter bar,
 * opportunity list and profile drawer.
 */

import { useMemo, useState } from "react";

import DashboardHeader from "@/components/DashboardHeader";
import FilterBar from "@/components/FilterBar";
import OpportunityCard from "@/components/OpportunityCard";
import ProfileSyncModal from "@/components/ProfileSyncModal";
import { applyFilters, type FilterState, INITIAL_FILTERS } from "@/lib/filter";
import { categoriesOf } from "@/lib/format";
import { HIGH_FIT_THRESHOLD, type Snapshot } from "@/lib/types";

export default function Dashboard({
  snapshot,
  loadError,
}: {
  snapshot: Snapshot;
  loadError: string | null;
}) {
  const [filters, setFilters] = useState<FilterState>(INITIAL_FILTERS);
  const [profileOpen, setProfileOpen] = useState(false);

  const categories = useMemo(
    () => categoriesOf(snapshot.opportunities),
    [snapshot.opportunities],
  );

  const visible = useMemo(
    () => applyFilters(snapshot.opportunities, filters),
    [snapshot.opportunities, filters],
  );

  return (
    <div className="min-h-screen">
      <DashboardHeader
        stats={snapshot.stats}
        generatedAt={snapshot.generated_at}
        highFitThreshold={HIGH_FIT_THRESHOLD}
        profileName={snapshot.profile.name}
        onOpenProfile={() => setProfileOpen(true)}
      />

      <FilterBar
        state={filters}
        categories={categories}
        resultCount={visible.length}
        totalCount={snapshot.opportunities.length}
        onChange={setFilters}
      />

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        {loadError ? (
          <p className="mb-5 rounded-lg bg-rose-500/10 px-4 py-3 text-sm text-rose-300 ring-1 ring-rose-500/20">
            {loadError}
          </p>
        ) : null}

        {snapshot.errors.length ? (
          <details className="mb-5 rounded-lg border border-amber-500/20 bg-amber-500/5 px-4 py-3">
            <summary className="cursor-pointer text-sm font-medium text-amber-300">
              {snapshot.errors.length} warning
              {snapshot.errors.length === 1 ? "" : "s"} from the last run
            </summary>
            <ul className="mt-2 space-y-1">
              {snapshot.errors.map((error, index) => (
                <li key={index} className="text-xs leading-relaxed text-amber-200/70">
                  {error}
                </li>
              ))}
            </ul>
          </details>
        ) : null}

        {visible.length ? (
          <div className="grid gap-3">
            {visible.map((opportunity) => (
              <OpportunityCard key={opportunity.id} opportunity={opportunity} />
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-[--color-edge] py-16 text-center">
            <p className="text-slate-400">No opportunities match these filters.</p>
            <button
              type="button"
              onClick={() => setFilters(INITIAL_FILTERS)}
              className="mt-3 text-sm text-sky-400 underline-offset-2 hover:underline"
            >
              Reset filters
            </button>
          </div>
        )}

        <footer className="mt-10 border-t border-[--color-edge] pt-5 text-xs text-slate-600">
          Sources: ESA Academy · Training &amp; Learning Programme ·
          jobs.esa.int. Always confirm details on the official ESA page before
          applying.
        </footer>
      </main>

      <ProfileSyncModal
        profile={snapshot.profile}
        open={profileOpen}
        onClose={() => setProfileOpen(false)}
      />
    </div>
  );
}
