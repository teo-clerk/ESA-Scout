/**
 * Shown before the agent has produced any data, or when the snapshot could not
 * be read. Explains the exact next step instead of rendering a blank page.
 */

export default function EmptyState({
  error,
  generatedAt,
}: {
  error: string | null;
  generatedAt: string;
}) {
  const hasRun = Boolean(generatedAt);

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col items-center justify-center px-6 text-center">
      <div className="mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-sky-500/10 ring-1 ring-sky-500/30">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className="h-7 w-7 text-sky-400"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="9" />
          <path d="M3.5 9h17M3.5 15h17M12 3a15 15 0 0 1 0 18a15 15 0 0 1 0-18Z" />
        </svg>
      </div>

      <h1 className="text-2xl font-semibold text-slate-100">ESA Scout</h1>
      <p className="mt-3 text-slate-400">
        {hasRun
          ? "The last run completed but found no opportunities."
          : "No scouting data yet."}
      </p>

      <div className="mt-8 w-full rounded-xl border border-[--color-edge] bg-[--color-panel] p-5 text-left">
        <p className="text-sm font-medium text-slate-300">Generate the data:</p>
        <pre className="mt-3 overflow-x-auto rounded-lg bg-black/40 px-4 py-3 text-sm text-sky-300">
          <code>python -m agent.main run</code>
        </pre>
        <p className="mt-4 text-sm text-slate-500">
          This scrapes the ESA sources, reads your CV and GitHub profile, scores
          each opportunity and writes{" "}
          <code className="text-slate-400">data/opportunities.json</code>.
        </p>
      </div>

      {error ? (
        <p className="mt-6 max-w-full overflow-x-auto rounded-lg bg-rose-500/10 px-4 py-3 text-left text-xs text-rose-300 ring-1 ring-rose-500/20">
          {error}
        </p>
      ) : null}
    </main>
  );
}
