/**
 * GET /api/sme — the cached SME snapshot as JSON.
 *
 * Used by the page's polling loop after an on-demand scan, and available for
 * anything else that wants the data without scraping the HTML.
 */

import { NextResponse } from "next/server";

import { loadSmeSnapshot } from "@/lib/sme-data";

export const dynamic = "force-dynamic";

export async function GET() {
  const { snapshot, error } = await loadSmeSnapshot();

  // A missing file is not a server fault: return the empty snapshot with the
  // explanation attached so the client can render a useful message.
  return NextResponse.json(
    error ? { ...snapshot, errors: [...snapshot.errors, error] } : snapshot,
    { headers: { "Cache-Control": "no-store" } },
  );
}
