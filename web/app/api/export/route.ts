/**
 * GET /api/export?type=opportunities|sme — the snapshot as a Markdown download.
 *
 * The CLI equivalent is `python -m agent.main export`, but a Vercel deployment
 * has no Python runtime, so the document is rendered here from the same JSON
 * the dashboard reads. `lib/markdown.ts` is a port of `agent/exporter.py`; both
 * produce the same file.
 */

import { loadSnapshot } from "@/lib/data";
import { loadSmeSnapshot } from "@/lib/sme-data";
import {
  exportFilename,
  renderOpportunities,
  renderSmeTargets,
  type ExportType,
} from "@/lib/markdown";
import { HIGH_FIT_THRESHOLD } from "@/lib/types";

// The underlying files are rewritten out-of-band by the agent, so never cache.
export const dynamic = "force-dynamic";
export const revalidate = 0;

const TYPES: ExportType[] = ["opportunities", "sme"];

export async function GET(request: Request): Promise<Response> {
  const requested = new URL(request.url).searchParams.get("type") ?? "opportunities";
  if (!TYPES.includes(requested as ExportType)) {
    return Response.json(
      { error: `Unknown export type "${requested}".`, expected: TYPES },
      { status: 400 },
    );
  }
  const type = requested as ExportType;

  const { markdown, empty, error } =
    type === "sme" ? await smeMarkdown() : await opportunitiesMarkdown();

  if (empty) {
    // Nothing on disk yet: expected before the first agent run, so answer with
    // an actionable 404 rather than handing the user a blank document.
    return Response.json(
      {
        error: error ?? "No data to export yet.",
        hint:
          type === "sme"
            ? "Run `python -m agent.main sme --evaluate` to generate the data."
            : "Run `python -m agent.main run` to generate the data.",
      },
      { status: 404 },
    );
  }

  return new Response(markdown, {
    headers: {
      // `charset` matters: the documents contain em dashes and accented names.
      "Content-Type": "text/markdown; charset=utf-8",
      "Content-Disposition": `attachment; filename="${exportFilename(type)}"`,
      "Cache-Control": "no-store, max-age=0",
    },
  });
}

interface Rendered {
  markdown: string;
  empty: boolean;
  error: string | null;
}

async function opportunitiesMarkdown(): Promise<Rendered> {
  const { snapshot, error } = await loadSnapshot();
  return {
    markdown: renderOpportunities(snapshot, HIGH_FIT_THRESHOLD),
    empty: snapshot.opportunities.length === 0,
    error,
  };
}

async function smeMarkdown(): Promise<Rendered> {
  const { snapshot, error } = await loadSmeSnapshot();
  return {
    markdown: renderSmeTargets(snapshot),
    empty: snapshot.companies.length === 0,
    error,
  };
}
