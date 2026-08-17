"use client";

/**
 * One opportunity: status, match meter, dates and an expandable AI analysis
 * panel (why apply / required skills / gaps / preparation checklist).
 */

import { useId, useState } from "react";

import MatchMeter from "@/components/MatchMeter";
import StatusBadge from "@/components/StatusBadge";
import { DEADLINE_STYLES, deadlineInfo, formatDate } from "@/lib/format";
import type { Opportunity } from "@/lib/types";

export default function OpportunityCard({
  opportunity,
}: {
  opportunity: Opportunity;
}) {
  const [expanded, setExpanded] = useState(false);
  const panelId = useId();

  const deadline = deadlineInfo(opportunity);
  const evaluation = opportunity.evaluation;
  const hasAnalysis = Boolean(
    evaluation &&
      !evaluation.error &&
      (evaluation.justification ||
        evaluation.why_apply.length ||
        evaluation.required_skills.length ||
        evaluation.checklist.length),
  );

  return (
    <article className="rounded-xl border border-[--color-edge] bg-[--color-panel] transition hover:border-slate-700">
      <div className="p-4 sm:p-5">
        <div className="flex items-start gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={opportunity.status} />
              <span className="text-xs text-slate-500">{opportunity.source_label}</span>
              {opportunity.kind ? (
                <span className="rounded bg-slate-500/10 px-2 py-0.5 text-xs text-slate-400">
                  {opportunity.kind}
                </span>
              ) : null}
            </div>

            <h3 className="mt-2 text-base font-semibold leading-snug text-slate-100">
              <a
                href={opportunity.url}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-sky-300"
              >
                {opportunity.title}
              </a>
            </h3>

            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
              <span className="text-slate-400">{opportunity.category}</span>
              {opportunity.location ? <span>{opportunity.location}</span> : null}
            </div>
          </div>

          <MatchMeter
            score={opportunity.match_score}
            evaluated={Boolean(evaluation && !evaluation.error)}
          />
        </div>

        {/* Dates */}
        <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
          {opportunity.activity_dates ? (
            <Field label="Activity">{opportunity.activity_dates}</Field>
          ) : null}
          <Field label="Deadline">
            <span className="text-slate-300">
              {formatDate(opportunity.deadline, opportunity.deadline_text || "—")}
            </span>
            <span className={`ml-2 ${DEADLINE_STYLES[deadline.tone]}`}>
              {deadline.days !== null ? `· ${deadline.label}` : ""}
            </span>
          </Field>
        </div>

        {/* Actions */}
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <a
            href={opportunity.url}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-lg bg-slate-700/50 px-3 py-1.5 text-sm font-medium text-slate-200 transition hover:bg-slate-700"
          >
            Open application page ↗
          </a>
          {hasAnalysis ? (
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              aria-expanded={expanded}
              aria-controls={panelId}
              className="rounded-lg px-3 py-1.5 text-sm font-medium text-sky-400 transition hover:bg-sky-500/10"
            >
              {expanded ? "Hide AI analysis" : "AI analysis"}
            </button>
          ) : evaluation?.error ? (
            <span className="text-xs text-amber-400/80">
              Analysis unavailable: {evaluation.error}
            </span>
          ) : null}
        </div>
      </div>

      {hasAnalysis && expanded ? (
        <div
          id={panelId}
          className="border-t border-[--color-edge] bg-[--color-panel-raised]/40 p-4 sm:p-5"
        >
          {evaluation!.justification ? (
            <p className="text-sm leading-relaxed text-slate-300">
              {evaluation!.justification}
            </p>
          ) : null}

          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <List title="Why apply" items={evaluation!.why_apply} tone="emerald" />
            <List
              title="Required skills"
              items={evaluation!.required_skills}
              tone="sky"
            />
          </div>

          {evaluation!.gaps.length ? (
            <div className="mt-4">
              <List title="Gaps to close" items={evaluation!.gaps} tone="amber" />
            </div>
          ) : null}

          {evaluation!.checklist.length ? (
            <div className="mt-5">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Preparation checklist
              </h4>
              <ol className="mt-2 space-y-2">
                {evaluation!.checklist.map((item, index) => (
                  <li
                    key={`${item.task}-${index}`}
                    className="flex gap-3 rounded-lg bg-black/20 px-3 py-2"
                  >
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-700 text-[11px] font-semibold text-slate-300">
                      {index + 1}
                    </span>
                    <div className="min-w-0">
                      <p className="text-sm text-slate-200">{item.task}</p>
                      {item.effort || item.done_when ? (
                        <p className="mt-0.5 text-xs text-slate-500">
                          {item.effort ? <span>{item.effort}</span> : null}
                          {item.effort && item.done_when ? " · " : null}
                          {item.done_when ? <span>Done when: {item.done_when}</span> : null}
                        </p>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          ) : null}

          {evaluation!.key_deadlines.length ? (
            <div className="mt-5">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Key deadlines
              </h4>
              <ul className="mt-2 space-y-1">
                {evaluation!.key_deadlines.map((item, index) => (
                  <li key={`${item.label}-${index}`} className="text-sm text-slate-300">
                    <span className="text-slate-500">{item.date || "TBC"}</span>
                    {" — "}
                    {item.label}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {evaluation!.model ? (
            <p className="mt-5 text-[11px] text-slate-600">
              Assessed by {evaluation!.model}
              {evaluation!.evaluated_at ? ` · ${evaluation!.evaluated_at}` : ""}
            </p>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <span className="mr-2 text-xs uppercase tracking-wide text-slate-600">
        {label}
      </span>
      <span className="text-slate-400">{children}</span>
    </div>
  );
}

const LIST_TONES: Record<string, string> = {
  emerald: "text-emerald-400",
  sky: "text-sky-400",
  amber: "text-amber-400",
};

function List({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: string;
}) {
  if (!items.length) return null;
  return (
    <div>
      <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h4>
      <ul className="mt-2 space-y-1.5">
        {items.map((item, index) => (
          <li key={`${item}-${index}`} className="flex gap-2 text-sm text-slate-300">
            <span className={`mt-1 text-[10px] ${LIST_TONES[tone] ?? ""}`}>●</span>
            <span className="min-w-0">{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
