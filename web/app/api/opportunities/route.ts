/**
 * GET /api/opportunities — the snapshot as JSON.
 *
 * Exists so the dashboard (or any other client) can refresh without a full page
 * load, and so external tooling can consume the scout's output.
 */

import { NextResponse } from "next/server";

import { loadSnapshot } from "@/lib/data";

// The file changes out-of-band (a cron job rewrites it), so never cache.
export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  const { snapshot, sourcePath, error } = await loadSnapshot();

  if (error && !sourcePath) {
    // Nothing on disk yet: this is expected before the first agent run, so it
    // is a 404 with an actionable message rather than a server error.
    return NextResponse.json(
      { error, hint: "Run `python -m agent.main run` to generate the data." },
      { status: 404 },
    );
  }
  if (error) {
    return NextResponse.json({ error }, { status: 500 });
  }

  return NextResponse.json(snapshot, {
    headers: { "Cache-Control": "no-store, max-age=0" },
  });
}
