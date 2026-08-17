/**
 * Presentation helpers shared by server and client components.
 *
 * Deadline state is computed here at render time rather than stored in the JSON
 * so it can never go stale between agent runs — the file is only rewritten
 * every 12 hours, but "3 days left" must still be right at 11 hours 59.
 */

import type { Opportunity, Status } from "./types";

export type DeadlineTone = "none" | "distant" | "soon" | "urgent" | "passed";

export interface DeadlineInfo {
  /** Whole days until the deadline; negative once elapsed. */
  days: number | null;
  tone: DeadlineTone;
  label: string;
}

const DAY_MS = 24 * 60 * 60 * 1000;
const URGENT_DAYS = 7;
const SOON_DAYS = 21;

/** Parse an ISO date as UTC midnight; returns null for empty/invalid input. */
export function parseIsoDate(value: string): Date | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return null;
  const date = new Date(
    Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])),
  );
  return Number.isNaN(date.getTime()) ? null : date;
}

export function daysUntil(iso: string, now: Date = new Date()): number | null {
  const target = parseIsoDate(iso);
  if (!target) return null;
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.round((target.getTime() - today) / DAY_MS);
}

export function deadlineInfo(
  opportunity: Opportunity,
  now: Date = new Date(),
): DeadlineInfo {
  const days = daysUntil(opportunity.deadline, now);

  if (days === null) {
    // No machine-readable date, but there may still be published wording.
    return {
      days: null,
      tone: "none",
      label: opportunity.deadline_text || "No deadline listed",
    };
  }
  if (days < 0) {
    const elapsed = Math.abs(days);
    return {
      days,
      tone: "passed",
      label: `Deadline passed ${elapsed} day${elapsed === 1 ? "" : "s"} ago`,
    };
  }
  if (days === 0) return { days, tone: "urgent", label: "Deadline today" };
  if (days === 1) return { days, tone: "urgent", label: "1 day left" };
  const tone: DeadlineTone =
    days <= URGENT_DAYS ? "urgent" : days <= SOON_DAYS ? "soon" : "distant";
  return { days, tone, label: `${days} days left` };
}

/** "5 April 2026" from an ISO date, falling back to the published wording. */
export function formatDate(iso: string, fallback = ""): string {
  const date = parseIsoDate(iso);
  if (!date) return fallback;
  return date.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** Relative wording for the last sync, e.g. "3 hours ago". */
export function relativeTime(iso: string, now: Date = new Date()): string {
  if (!iso) return "never";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "unknown";

  const seconds = Math.max(0, Math.round((now.getTime() - then.getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} day${days === 1 ? "" : "s"} ago`;
  const months = Math.round(days / 30);
  return `${months} month${months === 1 ? "" : "s"} ago`;
}

/** True when the sync is old enough that the data should not be trusted. */
export function isStale(iso: string, now: Date = new Date(), maxHours = 26): boolean {
  if (!iso) return true;
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return true;
  return now.getTime() - then.getTime() > maxHours * 60 * 60 * 1000;
}

export const STATUS_STYLES: Record<Status, string> = {
  Open: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  Pending: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  Closed: "bg-slate-500/15 text-slate-400 ring-slate-500/30",
  Unknown: "bg-slate-500/15 text-slate-400 ring-slate-500/30",
};

export const DEADLINE_STYLES: Record<DeadlineTone, string> = {
  urgent: "text-rose-300",
  soon: "text-amber-300",
  distant: "text-slate-400",
  passed: "text-slate-500",
  none: "text-slate-500",
};

/** Colour of the match meter, keyed to how strong the fit is. */
export function matchTone(score: number): { bar: string; text: string } {
  if (score >= 80) return { bar: "bg-emerald-400", text: "text-emerald-300" };
  if (score >= 60) return { bar: "bg-sky-400", text: "text-sky-300" };
  if (score >= 40) return { bar: "bg-amber-400", text: "text-amber-300" };
  if (score > 0) return { bar: "bg-slate-500", text: "text-slate-400" };
  return { bar: "bg-slate-700", text: "text-slate-500" };
}

/** Unique category names present in the data, alphabetically. */
export function categoriesOf(opportunities: Opportunity[]): string[] {
  return Array.from(new Set(opportunities.map((o) => o.category).filter(Boolean))).sort();
}
