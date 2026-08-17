/**
 * POST /api/sync — trigger a scouting run on demand.
 *
 * Dispatches the GitHub Actions workflow that runs the Python agent, so the
 * dashboard's "Sync now" button does not require shell access. The run writes
 * `data/opportunities.json`, commits it and redeploys, so results appear a
 * minute or two later rather than in this response.
 *
 * Configuration (Vercel project environment variables):
 *   GITHUB_REPO            owner/repo, e.g. "teoclerici/esa-scout"
 *   GITHUB_DISPATCH_TOKEN  a PAT with `actions: write` on that repository
 *   GITHUB_WORKFLOW_FILE   optional, defaults to "cron.yml"
 *   GITHUB_REF             optional branch, defaults to "main"
 *   SYNC_SECRET            optional; when set, callers must send x-sync-secret
 *
 * Without GITHUB_REPO/GITHUB_DISPATCH_TOKEN the endpoint reports 501 and the UI
 * falls back to simply re-reading the current data.
 */

import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const GITHUB_API = "https://api.github.com";

export async function POST(request: Request) {
  const repo = process.env.GITHUB_REPO;
  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const workflow = process.env.GITHUB_WORKFLOW_FILE || "cron.yml";
  const ref = process.env.GITHUB_REF || "main";
  const secret = process.env.SYNC_SECRET;

  // Triggering a workflow is a write action on a public URL. When a secret is
  // configured, require it; otherwise the endpoint is only as private as the
  // deployment itself.
  if (secret && request.headers.get("x-sync-secret") !== secret) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  if (!repo || !token) {
    return NextResponse.json(
      {
        error: "Remote sync is not configured.",
        hint:
          "Set GITHUB_REPO and GITHUB_DISPATCH_TOKEN in the Vercel project to " +
          "enable the sync button, or run `python -m agent.main run` locally.",
      },
      { status: 501 },
    );
  }

  try {
    const response = await fetch(
      `${GITHUB_API}/repos/${repo}/actions/workflows/${workflow}/dispatches`,
      {
        method: "POST",
        headers: {
          Accept: "application/vnd.github+json",
          Authorization: `Bearer ${token}`,
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref }),
        cache: "no-store",
      },
    );

    if (response.status === 204) {
      return NextResponse.json({
        ok: true,
        message:
          "Scouting run started. Results appear here once the workflow finishes.",
      });
    }

    const detail = await response.text();
    return NextResponse.json(
      {
        error: `GitHub returned ${response.status}`,
        detail: detail.slice(0, 400),
      },
      { status: 502 },
    );
  } catch (cause) {
    return NextResponse.json(
      { error: `Could not reach GitHub: ${(cause as Error).message}` },
      { status: 502 },
    );
  }
}
