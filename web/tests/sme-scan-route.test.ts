/**
 * POST /api/sync/sme/scan — the three outcomes the UI depends on.
 *
 * The route decides whether to dispatch a GitHub workflow, run the agent
 * locally, or decline and let the page keep showing cached results. Getting
 * that wrong either spends API credit silently or leaves the button dead, so
 * each branch is pinned here.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Typed so the call-tuple assertions below stay type-checked rather than `any`.
const spawn = vi.hoisted(() =>
  vi.fn(
    (
      _command: string,
      _args: readonly string[],
      _options: Record<string, unknown>,
    ) => ({ on: vi.fn(), unref: vi.fn() }),
  ),
);
vi.mock("node:child_process", () => ({ spawn }));

import { POST } from "@/app/api/sync/sme/scan/route";
import { redactSecrets } from "@/lib/redact";

function request(headers: Record<string, string> = {}): Request {
  return new Request("http://localhost/api/sync/sme/scan", {
    method: "POST",
    headers,
  });
}

beforeEach(() => {
  // A key must be present for anything past the first guard to run.
  vi.stubEnv("LLM_API_KEY", "test-key");
  vi.stubEnv("GITHUB_REPO", "");
  vi.stubEnv("GITHUB_DISPATCH_TOKEN", "");
  vi.stubEnv("SYNC_SECRET", "");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  spawn.mockClear();
});

describe("authorisation", () => {
  it("rejects a caller without the shared secret", async () => {
    vi.stubEnv("SYNC_SECRET", "s3cret");
    const response = await POST(request());
    expect(response.status).toBe(401);
    expect(spawn).not.toHaveBeenCalled();
  });

  it("rejects a caller with the wrong secret", async () => {
    vi.stubEnv("SYNC_SECRET", "s3cret");
    const response = await POST(request({ "x-sync-secret": "guess" }));
    expect(response.status).toBe(401);
  });

  it("accepts a caller with the right secret", async () => {
    vi.stubEnv("SYNC_SECRET", "s3cret");
    const response = await POST(request({ "x-sync-secret": "s3cret" }));
    expect(response.status).toBe(200);
  });
});

describe("without an LLM key", () => {
  it("declines to scan and explains why, rather than failing", async () => {
    vi.stubEnv("LLM_API_KEY", "");
    const response = await POST(request());
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.started).toBe(false);
    expect(payload.notice).toMatch(/LLM_API_KEY/);
    expect(payload.notice).toMatch(/cached/i);
    expect(spawn).not.toHaveBeenCalled();
  });
});

describe("workflow dispatch", () => {
  beforeEach(() => {
    vi.stubEnv("GITHUB_REPO", "owner/repo");
    vi.stubEnv("GITHUB_DISPATCH_TOKEN", "ghp_test");
  });

  it("dispatches the SME workflow and reports it started", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));

    const payload = await (await POST(request())).json();

    expect(payload).toMatchObject({ started: true, mode: "workflow" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(
      "https://api.github.com/repos/owner/repo/actions/workflows/sme.yml/dispatches",
    );
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({ ref: "main" });
    expect(spawn).not.toHaveBeenCalled();
  });

  it("honours the configured workflow file and branch", async () => {
    vi.stubEnv("GITHUB_SME_WORKFLOW", "custom.yml");
    vi.stubEnv("GITHUB_REF", "develop");
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));

    await POST(request());

    expect(fetchMock.mock.calls[0][0]).toContain("/workflows/custom.yml/");
    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({
      ref: "develop",
    });
  });

  it("reports a GitHub rejection as a 502 rather than a silent success", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("Not Found", { status: 404 }),
    );

    const response = await POST(request());
    const payload = await response.json();

    expect(response.status).toBe(502);
    expect(payload.started).toBe(false);
    expect(payload.error).toContain("404");
  });

  it("reports an unreachable GitHub as a 502", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("ENOTFOUND"));

    const response = await POST(request());
    expect(response.status).toBe(502);
    expect((await response.json()).error).toContain("ENOTFOUND");
  });

  it("never leaks the dispatch token into the response body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("boom ghp_test", { status: 500 }),
    );

    const body = await (await POST(request())).text();
    expect(body).not.toContain("ghp_test");
  });
});

describe("local runner", () => {
  it("spawns the agent with a fixed argv outside production", async () => {
    const payload = await (await POST(request())).json();

    expect(payload).toMatchObject({ started: true, mode: "local" });
    expect(spawn).toHaveBeenCalledTimes(1);
    const [command, args, options] = spawn.mock.calls[0];
    expect(args).toEqual(["-m", "agent.main", "sme", "--evaluate"]);
    expect(options).toMatchObject({ detached: true, shell: false });
    expect(typeof command).toBe("string");
  });

  it("uses PYTHON_BIN when the interpreter is not on PATH as python3", async () => {
    vi.stubEnv("PYTHON_BIN", "/repo/.venv/bin/python");
    await POST(request());
    expect(spawn.mock.calls[0][0]).toBe("/repo/.venv/bin/python");
  });

  it("prefers a configured workflow over the local runner", async () => {
    vi.stubEnv("GITHUB_REPO", "owner/repo");
    vi.stubEnv("GITHUB_DISPATCH_TOKEN", "ghp_test");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 }),
    );

    await POST(request());
    expect(spawn).not.toHaveBeenCalled();
  });
});

describe("production without dispatch configuration", () => {
  it("returns cached results with a notice instead of spawning a process", async () => {
    vi.stubEnv("NODE_ENV", "production");

    const response = await POST(request());
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.started).toBe(false);
    expect(payload.notice).toMatch(/not configured/i);
    expect(spawn).not.toHaveBeenCalled();
  });
});

describe("redactSecrets", () => {
  it("removes every occurrence of a credential", () => {
    const text = "token ghp_secretvalue used, ghp_secretvalue again";
    expect(redactSecrets(text, ["ghp_secretvalue"])).toBe(
      "token [redacted] used, [redacted] again",
    );
  });

  it("leaves unrelated text untouched", () => {
    expect(redactSecrets("nothing to hide", ["ghp_secretvalue"])).toBe(
      "nothing to hide",
    );
  });

  it("ignores empty and absent secrets", () => {
    expect(redactSecrets("abc", ["", undefined, null])).toBe("abc");
  });

  it("ignores values too short to be credentials", () => {
    // Redacting a 3-character value would mangle ordinary prose.
    expect(redactSecrets("a repo named repo", ["repo"])).toBe("a repo named repo");
  });
});
