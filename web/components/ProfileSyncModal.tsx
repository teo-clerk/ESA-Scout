"use client";

/**
 * Drawer showing what the agent knows about the user: CV highlights parsed from
 * the PDF and the GitHub repositories it detected. This is the transparency
 * surface — every match score is derived from exactly what is listed here.
 */

import { useEffect, useRef } from "react";

import type { Profile } from "@/lib/types";

interface Props {
  profile: Profile;
  open: boolean;
  onClose: () => void;
}

export default function ProfileSyncModal({ profile, open, onClose }: Props) {
  const panelRef = useRef<HTMLDivElement>(null);

  // Close on Escape and lock background scrolling while open.
  useEffect(() => {
    if (!open) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panelRef.current?.focus();

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [open, onClose]);

  if (!open) return null;

  const github = profile.github;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="Close profile panel"
        onClick={onClose}
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
      />

      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Profile and GitHub sync"
        tabIndex={-1}
        className="relative flex h-full w-full max-w-xl flex-col border-l border-[--color-edge] bg-[--color-panel] shadow-2xl focus:outline-none"
      >
        <div className="flex items-start justify-between border-b border-[--color-edge] p-5">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-slate-100">
              {profile.name || "Profile"}
            </h2>
            {profile.headline ? (
              <p className="mt-1 text-sm leading-relaxed text-slate-400">
                {profile.headline}
              </p>
            ) : null}
            {profile.source_file ? (
              <p className="mt-2 text-xs text-slate-600">
                Parsed from {profile.source_file}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="ml-4 shrink-0 rounded-lg px-2 py-1 text-slate-500 transition hover:bg-slate-800 hover:text-slate-300"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {profile.error ? (
            <p className="mb-5 rounded-lg bg-amber-500/10 px-3 py-2 text-sm text-amber-300 ring-1 ring-amber-500/20">
              {profile.error}
            </p>
          ) : null}

          <Section title="Skills detected">
            {profile.skills.length ? (
              <div className="flex flex-wrap gap-1.5">
                {profile.skills.map((skill) => (
                  <span
                    key={skill}
                    className="rounded-md bg-slate-500/10 px-2 py-1 text-xs text-slate-300 ring-1 ring-slate-500/20"
                  >
                    {skill}
                  </span>
                ))}
              </div>
            ) : (
              <Empty>No skills section found in the CV.</Empty>
            )}
          </Section>

          <Section title="Education">
            {profile.education.length ? (
              <ul className="space-y-2">
                {profile.education.map((item, index) => (
                  <li key={index} className="text-sm leading-relaxed text-slate-300">
                    {item}
                  </li>
                ))}
              </ul>
            ) : (
              <Empty>No education section found.</Empty>
            )}
          </Section>

          <Section title="Experience & projects">
            {profile.highlights.length ? (
              <ul className="space-y-2.5">
                {profile.highlights.map((item, index) => (
                  <li
                    key={index}
                    className="rounded-lg bg-black/20 px-3 py-2 text-sm leading-relaxed text-slate-300"
                  >
                    {item}
                  </li>
                ))}
              </ul>
            ) : (
              <Empty>No experience or projects found.</Empty>
            )}
          </Section>

          <Section
            title={
              github.username ? `GitHub · @${github.username}` : "GitHub"
            }
          >
            {github.error ? (
              <Empty>{github.error}</Empty>
            ) : github.repos.length ? (
              <>
                {github.languages.length ? (
                  <p className="mb-3 text-xs text-slate-500">
                    Primary languages: {github.languages.join(", ")}
                  </p>
                ) : null}
                <ul className="space-y-2">
                  {github.repos.map((repo) => (
                    <li
                      key={repo.name}
                      className="rounded-lg border border-[--color-edge] px-3 py-2"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <a
                          href={repo.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="truncate text-sm font-medium text-sky-300 hover:underline"
                        >
                          {repo.name}
                        </a>
                        <span className="shrink-0 text-xs text-slate-500">
                          {repo.language || "—"}
                          {repo.stars > 0 ? ` · ★ ${repo.stars}` : ""}
                        </span>
                      </div>
                      {repo.description ? (
                        <p className="mt-1 text-xs leading-relaxed text-slate-500">
                          {repo.description}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <Empty>No repositories detected.</Empty>
            )}
          </Section>
        </div>
      </div>
    </div>
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
    <section className="mb-7">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h3>
      {children}
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-slate-600">{children}</p>;
}
