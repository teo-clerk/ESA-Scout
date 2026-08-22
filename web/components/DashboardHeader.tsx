"use client";

/**
 * System header: live status, last sync, headline metrics and the manual
 * sync trigger.
 */

import { useEffect, useState } from "react";

import ViewTabs from "@/components/ViewTabs";
import { isStale, relativeTime } from "@/lib/format";
import type { Stats } from "@/lib/types";

interface Props {
  stats: Stats;
  generatedAt: string;
  highFitThreshold: number;
  onOpenProfile: () => void;
  profileName: string;
}

type SyncState =
  | { kind: "idle" }
  | { kind: "running" }
  | { kind: "done"; message: string }
  | { kind: "error"; message: string };

export default function DashboardHeader({
  stats,
  generatedAt,
  highFitThreshold,
  onOpenProfile,
  profileName,
}: Props) {
  const [sync, setSync] = useState<SyncState>({ kind: "idle" });

  // `relativeTime` depends on the current clock, which differs between the
  // server render and the browser. Compute it after mount to avoid a hydration
  // mismatch, showing the absolute timestamp until then.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const stale = mounted && isStale(generatedAt);
  const syncedLabel = mounted
    ? relativeTime(generatedAt)
    : generatedAt || "never";

  async function handleSync() {
    setSync({ kind: "running" });
    try {
      const response = await fetch("/api/sync", { method: "POST" });
      const payload = await response.json().catch(() => ({}));

      if (response.ok) {
        setSync({
          kind: "done",
          message: payload.message ?? "Scouting run started.",
        });
        // The workflow takes a while; reload so the user sees fresh data once
        // the redeploy lands.
        setTimeout(() => window.location.reload(), 4000);
        return;
      }
      setSync({
        kind: "error",
        message: payload.hint ?? payload.error ?? `Sync failed (${response.status}).`,
      });
    } catch (cause) {
      setSync({ kind: "error", message: (cause as Error).message });
    }
  }

  return (
    <header className="border-b border-[--color-edge] bg-[--color-panel]/60 backdrop-blur">
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <ViewTabs />

        <div className="mt-5 flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-3">
              <span
                className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${
                  stale ? "bg-amber-400" : "bg-emerald-400"
                }`}
                aria-hidden="true"
              />
              <h1 className="truncate text-xl font-semibold tracking-tight text-slate-100">
                ESA Scout
              </h1>
              <span className="rounded-full bg-slate-500/10 px-2.5 py-0.5 text-xs font-medium text-slate-400 ring-1 ring-slate-500/20">
                {stale ? "Sync overdue" : "Monitoring"}
              </span>
            </div>
            <p className="mt-1.5 text-sm text-slate-500">
              Last sync <span className="text-slate-400">{syncedLabel}</span>
              {profileName ? (
                <>
                  {" · matched against "}
                  <span className="text-slate-400">{profileName}</span>
                </>
              ) : null}
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onOpenProfile}
              className="rounded-lg border border-[--color-edge] bg-[--color-panel-raised] px-3.5 py-2 text-sm font-medium text-slate-300 transition hover:border-slate-600 hover:text-slate-100"
            >
              Profile &amp; GitHub
            </button>
            <button
              type="button"
              onClick={handleSync}
              disabled={sync.kind === "running"}
              className="rounded-lg bg-sky-500 px-3.5 py-2 text-sm font-semibold text-slate-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {sync.kind === "running" ? "Syncing…" : "Sync now"}
            </button>
          </div>
        </div>

        {sync.kind === "done" || sync.kind === "error" ? (
          <p
            role="status"
            className={`mt-3 rounded-lg px-3 py-2 text-sm ring-1 ${
              sync.kind === "done"
                ? "bg-emerald-500/10 text-emerald-300 ring-emerald-500/20"
                : "bg-amber-500/10 text-amber-300 ring-amber-500/20"
            }`}
          >
            {sync.message}
          </p>
        ) : null}

        <dl className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Metric label="Open now" value={stats.open} tone="emerald" />
          <Metric
            label={`High fit ≥ ${highFitThreshold}%`}
            value={stats.high_fit}
            tone="sky"
          />
          <Metric label="Pending cycles" value={stats.pending} tone="amber" />
          <Metric label="Tracked total" value={stats.total} tone="slate" />
        </dl>
      </div>
    </header>
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
  tone: keyof typeof TONES | string;
}) {
  return (
    <div className="rounded-xl border border-[--color-edge] bg-[--color-panel-raised]/60 px-4 py-3">
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </dt>
      <dd className={`mt-1 text-2xl font-semibold tabular-nums ${TONES[tone] ?? TONES.slate}`}>
        {value}
      </dd>
    </div>
  );
}
