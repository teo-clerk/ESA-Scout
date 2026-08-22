/**
 * POST /api/sync/sme/scan — run the ESA-star SME scan on demand.
 *
 * Three outcomes, in priority order:
 *
 *   1. **Workflow dispatch** (production). With GITHUB_REPO and
 *      GITHUB_DISPATCH_TOKEN set, this triggers the `sme.yml` workflow, which
 *      scans, ranks, commits the JSON and redeploys.
 *   2. **Local runner** (development). Outside production, spawn
 *      `python -m agent.main sme --evaluate` in the repository. Detached, so
 *      the request returns immediately; the client polls GET /api/sme.
 *   3. **Cached results** — when neither is possible, or when no LLM key is
 *      configured, return `started: false` with a `notice` explaining why. The
 *      page keeps showing the cached companies.
 *
 * Configuration (Vercel project environment variables):
 *   GITHUB_REPO             owner/repo
 *   GITHUB_DISPATCH_TOKEN   PAT with `actions: write`
 *   GITHUB_SME_WORKFLOW     optional, defaults to "sme.yml"
 *   GITHUB_REF              optional branch, defaults to "main"
 *   SYNC_SECRET             optional; when set, callers must send x-sync-secret
 *   LLM_API_KEY             presence is checked so the UI can explain an
 *                           unranked result before spending a scan on it
 */

import { NextResponse } from "next/server";

import { redactSecrets } from "@/lib/redact";

export const dynamic = "force-dynamic";

const GITHUB_API = "https://api.github.com";

export async function POST(request: Request) {
  const secret = process.env.SYNC_SECRET;
  if (secret && request.headers.get("x-sync-secret") !== secret) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  if (!process.env.LLM_API_KEY) {
    return NextResponse.json({
      started: false,
      notice:
        "No LLM_API_KEY is configured, so a scan could only re-list companies " +
        "without ranking them. Showing the cached results instead.",
    });
  }

  const repo = process.env.GITHUB_REPO;
  const token = process.env.GITHUB_DISPATCH_TOKEN;

  if (repo && token) {
    return dispatchWorkflow(repo, token);
  }

  if (process.env.NODE_ENV !== "production") {
    return runLocally();
  }

  return NextResponse.json({
    started: false,
    notice:
      "On-demand scanning is not configured for this deployment. Set " +
      "GITHUB_REPO and GITHUB_DISPATCH_TOKEN, or run " +
      "`python -m agent.main sme --evaluate` locally. Showing cached results.",
  });
}

async function dispatchWorkflow(repo: string, token: string) {
  const workflow = process.env.GITHUB_SME_WORKFLOW || "sme.yml";
  const ref = process.env.GITHUB_REF || "main";

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
        started: true,
        mode: "workflow",
        message:
          "SME scan started on GitHub Actions. Results appear here once it finishes (a few minutes).",
      });
    }

    // Forward enough detail to debug a bad repo or workflow name, but never
    // the credentials themselves — this endpoint is publicly reachable.
    const detail = redactSecrets(await response.text(), [
      token,
      process.env.SYNC_SECRET,
    ]);
    return NextResponse.json(
      {
        started: false,
        error: `GitHub returned ${response.status}`,
        detail: detail.slice(0, 400),
      },
      { status: 502 },
    );
  } catch (cause) {
    return NextResponse.json(
      {
        started: false,
        error: `Could not reach GitHub: ${(cause as Error).message}`,
      },
      { status: 502 },
    );
  }
}

async function runLocally() {
  try {
    const { spawn } = await import("node:child_process");
    const path = await import("node:path");

    const repoRoot = path.join(process.cwd(), "..");
    const python = process.env.PYTHON_BIN || "python3";

    // Fixed argv, never shell-interpolated and never built from request data:
    // there is no injection surface here.
    //
    // `turbopackIgnore` keeps the bundler from statically tracing this call:
    // the repository-root `cwd` is dynamic, and without the hint Next.js pulls
    // the entire project into the serverless bundle. This branch never runs in
    // production anyway — the guard above returns before reaching it.
    const child = spawn(
      /* turbopackIgnore: true */ python,
      ["-m", "agent.main", "sme", "--evaluate"],
      {
        cwd: repoRoot,
        detached: true,
        stdio: "ignore",
        shell: false,
      },
    );
    child.on("error", (cause) => {
      console.error("SME scan could not start:", cause);
    });
    child.unref();

    return NextResponse.json({
      started: true,
      mode: "local",
      message:
        "SME scan started locally. It takes a few minutes; results appear here automatically.",
    });
  } catch (cause) {
    return NextResponse.json(
      {
        started: false,
        error: `Could not start the local scan: ${(cause as Error).message}`,
      },
      { status: 500 },
    );
  }
}
