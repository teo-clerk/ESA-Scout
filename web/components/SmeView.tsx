"use client";

/**
 * Client shell for the SME target list: owns filter state, the on-demand scan
 * and the polling that picks the results up when the scan finishes.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import SmeCard from "@/components/SmeCard";
import ViewTabs from "@/components/ViewTabs";
import { isStale, relativeTime } from "@/lib/format";
import {
  applySmeFilters,
  countriesOf,
  domainsOf,
  INITIAL_SME_FILTERS,
  isSmeFiltered,
  type SmeFilterState,
} from "@/lib/sme-filter";
import {
  countryFlag,
  type SmeSnapshot,
  type SmeSortKey,
} from "@/lib/sme-types";

/** How long to watch for a triggered scan to land, and how often to look. */
const POLL_INTERVAL_MS = 5000;
const POLL_TIMEOUT_MS = 5 * 60 * 1000;

type ScanState =
  | { kind: "idle" }
  | { kind: "running"; message: string }
  | { kind: "done"; message: string }
  | { kind: "notice"; message: string }
  | { kind: "error"; message: string };

export default function SmeView({
  initialSnapshot,
  loadError,
}: {
  initialSnapshot: SmeSnapshot;
  loadError: string | null;
}) {
  const [snapshot, setSnapshot] = useState(initialSnapshot);
  const [filters, setFilters] = useState<SmeFilterState>(INITIAL_SME_FILTERS);
  const [scan, setScan] = useState<ScanState>({ kind: "idle" });

  // Relative timestamps differ between the server render and the browser.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    },
    [],
  );

  const companies = snapshot.companies;
  const domains = useMemo(() => domainsOf(companies), [companies]);
  const countries = useMemo(() => countriesOf(companies), [companies]);
  const visible = useMemo(
    () => applySmeFilters(companies, filters),
    [companies, filters],
  );

  const update = useCallback(
    (patch: Partial<SmeFilterState>) =>
      setFilters((current) => ({ ...current, ...patch })),
    [],
  );

  /** Poll the cached snapshot until `last_analyzed` moves or time runs out. */
  const pollForResults = useCallback(
    (previousTimestamp: string, deadline: number) => {
      pollTimer.current = setTimeout(async () => {
        try {
          const response = await fetch("/api/sme", { cache: "no-store" });
          if (response.ok) {
            const payload = (await response.json()) as SmeSnapshot;
            if (payload.last_analyzed !== previousTimestamp) {
              setSnapshot(payload);
              setScan({
                kind: "done",
                message: `Scan complete — ${payload.stats.matched} companies matched, ${payload.stats.evaluated} ranked.`,
              });
              return;
            }
          }
        } catch {
          // A failed poll is not a failed scan; keep waiting.
        }
        if (Date.now() < deadline) {
          pollForResults(previousTimestamp, deadline);
        } else {
          setScan({
            kind: "notice",
            message:
              "The scan is taking longer than expected. Reload this page in a few minutes to see the results.",
          });
        }
      }, POLL_INTERVAL_MS);
    },
    [],
  );

  async function handleScan() {
    setScan({ kind: "running", message: "Starting the ESA-star scan…" });
    try {
      const response = await fetch("/api/sync/sme/scan", { method: "POST" });
      const payload = await response.json().catch(() => ({}));

      if (response.ok && payload.started) {
        setScan({
          kind: "running",
          message: payload.message ?? "Scan running — results appear here when it finishes.",
        });
        pollForResults(snapshot.last_analyzed, Date.now() + POLL_TIMEOUT_MS);
        return;
      }

      // Not started: show the cached data with an explicit reason.
      setScan({
        kind: response.ok ? "notice" : "error",
        message:
          payload.notice ??
          payload.hint ??
          payload.error ??
          `Could not start a scan (${response.status}).`,
      });
    } catch (cause) {
      setScan({ kind: "error", message: (cause as Error).message });
    }
  }

  const analysedLabel = mounted
    ? relativeTime(snapshot.last_analyzed)
    : snapshot.last_analyzed || "never";
  const stale = mounted && isStale(snapshot.last_analyzed, new Date(), 24 * 30);

  return (
    <div className="min-h-screen">
      <header className="border-b border-[--color-edge] bg-[--color-panel]/60 backdrop-blur">
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
          <ViewTabs />

          <div className="mt-5 flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <h1 className="text-xl font-semibold tracking-tight text-slate-100">
                SME Internship Targets
              </h1>
              <p className="mt-1.5 text-sm text-slate-500">
                ESA-registered SMEs in{" "}
                {snapshot.countries.join(" and ") || "Spain and Italy"}, ranked
                for a speculative{" "}
                <span className="text-slate-400">
                  {snapshot.target_term || "summer"}
                </span>{" "}
                internship · analysed{" "}
                <span className={stale ? "text-amber-400" : "text-slate-400"}>
                  {analysedLabel}
                </span>
              </p>
            </div>

            <button
              type="button"
              onClick={handleScan}
              disabled={scan.kind === "running"}
              className="rounded-lg bg-sky-500 px-3.5 py-2 text-sm font-semibold text-slate-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {scan.kind === "running" ? "Analysing…" : "Analyze best SME matches"}
            </button>
          </div>

          {scan.kind !== "idle" ? (
            <p
              role="status"
              className={`mt-3 rounded-lg px-3 py-2 text-sm ring-1 ${
                scan.kind === "done"
                  ? "bg-emerald-500/10 text-emerald-300 ring-emerald-500/20"
                  : scan.kind === "error"
                    ? "bg-rose-500/10 text-rose-300 ring-rose-500/20"
                    : "bg-amber-500/10 text-amber-300 ring-amber-500/20"
              }`}
            >
              {scan.message}
            </p>
          ) : null}

          <dl className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Metric label="Matched" value={snapshot.stats.matched} tone="slate" />
            <Metric
              label={`Strong fit ≥ ${snapshot.strong_fit_threshold}%`}
              value={snapshot.stats.strong_fit}
              tone="sky"
            />
            <Metric label="AI-ranked" value={snapshot.stats.evaluated} tone="emerald" />
            <Metric label="Scanned" value={snapshot.stats.scanned} tone="slate" />
          </dl>
        </div>
      </header>

      <div className="sticky top-0 z-10 border-b border-[--color-edge] bg-[--color-void]/85 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-2 px-4 py-3 sm:px-6 lg:px-8">
          <input
            type="search"
            value={filters.query}
            onChange={(event) => update({ query: event.target.value })}
            placeholder="Search companies, cities, domains…"
            aria-label="Search companies"
            className="min-w-[12rem] flex-1 rounded-lg border border-[--color-edge] bg-[--color-panel-raised] px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600"
          />

          <Select
            label="Country"
            value={filters.country}
            onChange={(value) => update({ country: value })}
            options={[
              { value: "All", label: "All countries" },
              ...countries.map((code) => ({
                value: code,
                label: `${countryFlag(code)} ${code}`.trim(),
              })),
            ]}
          />

          <Select
            label="Domain"
            value={filters.domain}
            onChange={(value) => update({ domain: value })}
            options={[
              { value: "All", label: "All domains" },
              ...domains.map((domain) => ({ value: domain, label: domain })),
            ]}
          />

          <Select
            label="Sort by"
            value={filters.sort}
            onChange={(value) => update({ sort: value as SmeSortKey })}
            options={[
              { value: "fit", label: "Best fit" },
              { value: "domains", label: "Most domains" },
              { value: "name", label: "Name" },
            ]}
          />

          <label className="flex items-center gap-2 rounded-lg border border-[--color-edge] bg-[--color-panel-raised] px-3 py-2 text-sm text-slate-400">
            <input
              type="checkbox"
              checked={filters.rankedOnly}
              onChange={(event) => update({ rankedOnly: event.target.checked })}
              className="h-3.5 w-3.5 accent-sky-500"
            />
            Ranked only
          </label>

          <span className="ml-auto text-xs tabular-nums text-slate-500">
            {visible.length} of {companies.length}
          </span>

          {isSmeFiltered(filters) ? (
            <button
              type="button"
              onClick={() => setFilters(INITIAL_SME_FILTERS)}
              className="text-xs text-sky-400 underline-offset-2 hover:underline"
            >
              Reset
            </button>
          ) : null}
        </div>
      </div>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        {loadError ? (
          <p className="mb-5 rounded-lg bg-rose-500/10 px-4 py-3 text-sm text-rose-300 ring-1 ring-rose-500/20">
            {loadError}
          </p>
        ) : null}

        {companies.length && !snapshot.evaluated ? (
          <p className="mb-5 rounded-lg bg-amber-500/10 px-4 py-3 text-sm text-amber-300 ring-1 ring-amber-500/20">
            These companies matched the keyword filter but have not been ranked
            by the AI yet. Set <code className="font-mono">LLM_API_KEY</code> and
            run <code className="font-mono">python -m agent.main sme --evaluate</code>.
          </p>
        ) : null}

        {snapshot.errors.length ? (
          <details className="mb-5 rounded-lg border border-amber-500/20 bg-amber-500/5 px-4 py-3">
            <summary className="cursor-pointer text-sm font-medium text-amber-300">
              {snapshot.errors.length} warning
              {snapshot.errors.length === 1 ? "" : "s"} from the last scan
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
            {visible.map((company) => (
              <SmeCard
                key={company.id}
                company={company}
                strongFitThreshold={snapshot.strong_fit_threshold}
                onSelectDomain={(domain) => update({ domain })}
              />
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-[--color-edge] py-16 text-center">
            <p className="text-slate-400">
              {companies.length
                ? "No companies match these filters."
                : "No SME matches yet. Run a scan to populate this list."}
            </p>
            {isSmeFiltered(filters) ? (
              <button
                type="button"
                onClick={() => setFilters(INITIAL_SME_FILTERS)}
                className="mt-3 text-sm text-sky-400 underline-offset-2 hover:underline"
              >
                Reset filters
              </button>
            ) : null}
          </div>
        )}

        <footer className="mt-10 border-t border-[--color-edge] pt-5 text-xs leading-relaxed text-slate-600">
          Source: ESA-star public entity directory. Domain tags are inferred
          from each company&apos;s own English description — ESA-star publishes
          no structured activity field. None of these companies has advertised
          an internship; treat every one as a cold approach.
        </footer>
      </main>
    </div>
  );
}

const TONES: Record<string, string> = {
  emerald: "text-emerald-300",
  sky: "text-sky-300",
  amber: "text-amber-300",
  slate: "text-slate-300",
};

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: string;
}) {
  return (
    <div className="rounded-xl border border-[--color-edge] bg-[--color-panel-raised]/60 px-4 py-3">
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </dt>
      <dd
        className={`mt-1 text-2xl font-semibold tabular-nums ${TONES[tone] ?? TONES.slate}`}
      >
        {value}
      </dd>
    </div>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label className="flex items-center gap-2 text-xs text-slate-500">
      <span className="sr-only sm:not-sr-only">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-label={label}
        className="rounded-lg border border-[--color-edge] bg-[--color-panel-raised] px-3 py-2 text-sm text-slate-200"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
