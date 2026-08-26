"use client";

/**
 * Downloads the current view as Markdown from `/api/export`.
 *
 * A plain anchor would be simpler, but the route answers 404 with a JSON
 * explanation when the agent has not run yet; the browser would navigate away
 * from the dashboard to show it. Fetching lets the failure stay inline.
 */

import { useState } from "react";

import type { ExportType } from "@/lib/markdown";

type State = { kind: "idle" } | { kind: "working" } | { kind: "error"; message: string };

export default function ExportButton({
  type,
  disabled = false,
}: {
  type: ExportType;
  disabled?: boolean;
}) {
  const [state, setState] = useState<State>({ kind: "idle" });

  async function handleExport() {
    setState({ kind: "working" });
    try {
      const response = await fetch(`/api/export?type=${type}`, { cache: "no-store" });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        setState({
          kind: "error",
          message: payload.hint ?? payload.error ?? `Export failed (${response.status}).`,
        });
        return;
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filenameFrom(response) ?? `esa_${type}.md`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      // Revoking immediately can cancel the download in some browsers.
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
      setState({ kind: "idle" });
    } catch (cause) {
      setState({ kind: "error", message: (cause as Error).message });
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={handleExport}
        disabled={disabled || state.kind === "working"}
        title="Download this view as a Markdown document"
        className="rounded-lg border border-[--color-edge] bg-[--color-panel-raised] px-3.5 py-2 text-sm font-medium text-slate-300 transition hover:border-slate-600 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {state.kind === "working" ? "Exporting…" : "Export .md"}
      </button>
      {state.kind === "error" ? (
        <span role="status" className="text-xs text-amber-300">
          {state.message}
        </span>
      ) : null}
    </>
  );
}

/** Read the server-chosen filename so the CLI and the browser agree. */
function filenameFrom(response: Response): string | null {
  const header = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(header);
  return match ? match[1] : null;
}
