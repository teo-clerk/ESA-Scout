"use client";

/**
 * One ESA-star SME rendered as an outreach target: who they are, why they fit,
 * and what to say in the email.
 */

import { useState } from "react";

import MatchMeter from "@/components/MatchMeter";
import { countryFlag, type Sme } from "@/lib/sme-types";

interface Props {
  company: Sme;
  strongFitThreshold: number;
  /** Clicking a domain tag filters the list by it. */
  onSelectDomain?: (domain: string) => void;
}

export default function SmeCard({
  company,
  strongFitThreshold,
  onSelectDomain,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const evaluation = company.evaluation;
  const ranked = evaluation !== null && !evaluation.error;
  const strong = ranked && company.fit_score >= strongFitThreshold;
  const location = [company.city, company.country].filter(Boolean).join(", ");
  const detailsId = `sme-details-${company.id}`;

  return (
    <article
      className={`rounded-xl border bg-[--color-panel]/70 transition hover:border-slate-600 ${
        strong ? "border-sky-500/30" : "border-[--color-edge]"
      }`}
    >
      <div className="flex items-start gap-4 p-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span aria-hidden="true" className="text-base leading-none">
              {countryFlag(company.country_code)}
            </span>
            <h3 className="min-w-0 text-base font-semibold text-slate-100">
              {company.name}
            </h3>
            {strong ? (
              <span className="rounded-full bg-sky-500/10 px-2 py-0.5 text-xs font-semibold text-sky-300 ring-1 ring-inset ring-sky-500/25">
                Strong fit
              </span>
            ) : null}
          </div>

          <p className="mt-1 text-xs text-slate-500">
            <span className="sr-only">Location: </span>
            {location || "Location not published"}
            {company.entity_size && company.entity_size !== "TBD" ? (
              <> · {company.entity_size}</>
            ) : null}
          </p>

          {company.domains.length ? (
            <ul className="mt-2.5 flex flex-wrap gap-1.5">
              {company.domains.map((domain) => (
                <li key={domain}>
                  <button
                    type="button"
                    onClick={() => onSelectDomain?.(domain)}
                    title={`Filter by ${domain}`}
                    className="rounded-md bg-slate-500/10 px-2 py-0.5 text-xs text-slate-400 ring-1 ring-inset ring-slate-500/20 transition hover:text-slate-200 hover:ring-slate-500/40"
                  >
                    {domain}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}

          {evaluation?.suggested_role ? (
            <p className="mt-3 text-sm text-slate-300">
              <span className="text-slate-500">Pitch yourself as: </span>
              {evaluation.suggested_role}
            </p>
          ) : null}
        </div>

        <MatchMeter score={company.fit_score} evaluated={ranked} />
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-[--color-edge] px-4 py-2.5">
        <button
          type="button"
          onClick={() => setExpanded((open) => !open)}
          aria-expanded={expanded}
          aria-controls={detailsId}
          className="text-sm text-slate-400 transition hover:text-slate-200"
        >
          {expanded ? "Hide details" : "Details & outreach"}
        </button>

        {company.website ? (
          <a
            href={company.website}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm font-medium text-sky-400 underline-offset-2 hover:underline"
          >
            Website ↗
          </a>
        ) : (
          <span className="text-sm text-slate-600">No website published</span>
        )}

        <a
          href={company.detail_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm text-slate-500 underline-offset-2 hover:text-slate-300 hover:underline"
        >
          ESA-star record ↗
        </a>
      </div>

      {expanded ? (
        <div id={detailsId} className="space-y-4 border-t border-[--color-edge] px-4 py-4">
          {evaluation?.rationale ? (
            <p className="text-sm leading-relaxed text-slate-300">
              {evaluation.rationale}
            </p>
          ) : null}

          {evaluation?.error ? (
            <p className="rounded-lg bg-amber-500/10 px-3 py-2 text-xs text-amber-300 ring-1 ring-amber-500/20">
              AI ranking failed for this company: {evaluation.error}
            </p>
          ) : null}

          {!evaluation ? (
            <p className="text-sm text-slate-500">
              Not ranked yet — this company matched the keyword filter but fell
              outside the evaluation budget for the last run.
            </p>
          ) : null}

          {evaluation?.focus_areas?.length ? (
            <Section title="Focus areas to emphasise">
              <ul className="flex flex-wrap gap-1.5">
                {evaluation.focus_areas.map((area) => (
                  <li
                    key={area}
                    className="rounded-md bg-sky-500/10 px-2 py-0.5 text-xs text-sky-300 ring-1 ring-inset ring-sky-500/20"
                  >
                    {area}
                  </li>
                ))}
              </ul>
            </Section>
          ) : null}

          {evaluation?.outreach_tips?.length ? (
            <Section title="How to approach them">
              <ul className="space-y-1.5">
                {evaluation.outreach_tips.map((tip) => (
                  <li
                    key={tip}
                    className="flex gap-2 text-sm leading-relaxed text-slate-300"
                  >
                    <span aria-hidden="true" className="text-sky-500">
                      →
                    </span>
                    <span>{tip}</span>
                  </li>
                ))}
              </ul>
            </Section>
          ) : null}

          {company.description ? (
            <Section title="What they say about themselves">
              <p className="text-sm leading-relaxed text-slate-400">
                {company.description}
              </p>
            </Section>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h4>
      {children}
    </section>
  );
}
