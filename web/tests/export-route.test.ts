/**
 * GET /api/export — the contract the download button depends on.
 *
 * The response headers are the feature: without the right Content-Disposition
 * the browser renders the Markdown instead of saving it, and without the 404
 * branch a user who has never run the agent silently downloads an empty file.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

const loadSnapshot = vi.hoisted(() => vi.fn());
const loadSmeSnapshot = vi.hoisted(() => vi.fn());
vi.mock("@/lib/data", () => ({ loadSnapshot }));
vi.mock("@/lib/sme-data", () => ({ loadSmeSnapshot }));

import { GET } from "@/app/api/export/route";
import { EMPTY_SNAPSHOT } from "@/lib/types";
import { EMPTY_SME_SNAPSHOT } from "@/lib/sme-types";
import { makeOpportunity, makeRankedSme } from "./factories";

function request(query = ""): Request {
  return new Request(`http://localhost/api/export${query}`);
}

beforeEach(() => {
  vi.clearAllMocks();
  loadSnapshot.mockResolvedValue({
    snapshot: {
      ...EMPTY_SNAPSHOT,
      opportunities: [makeOpportunity({ title: "Navigation Training Course" })],
    },
    sourcePath: "/data/opportunities.json",
    error: null,
  });
  loadSmeSnapshot.mockResolvedValue({
    snapshot: {
      ...EMPTY_SME_SNAPSHOT,
      companies: [makeRankedSme(85, { name: "Acme Geospatial SL" })],
    },
    sourcePath: "/data/sme_matches.json",
    error: null,
  });
});

describe("opportunities export", () => {
  it("is the default when no type is given", async () => {
    const response = await GET(request());
    expect(response.status).toBe(200);
    expect(await response.text()).toContain("# ESA Scout — Opportunities");
  });

  it("serves Markdown as a dated attachment", async () => {
    const response = await GET(request("?type=opportunities"));

    expect(response.headers.get("Content-Type")).toBe("text/markdown; charset=utf-8");
    expect(response.headers.get("Content-Disposition")).toMatch(
      /^attachment; filename="esa_opportunities_\d{4}-\d{2}-\d{2}\.md"$/,
    );
    expect(response.headers.get("Cache-Control")).toContain("no-store");
    expect(await response.text()).toContain("Navigation Training Course");
  });

  it("answers 404 with a runnable hint before the first agent run", async () => {
    loadSnapshot.mockResolvedValue({
      snapshot: EMPTY_SNAPSHOT,
      sourcePath: null,
      error: "No opportunities.json found.",
    });

    const response = await GET(request("?type=opportunities"));
    const payload = await response.json();

    expect(response.status).toBe(404);
    expect(payload.hint).toContain("python -m agent.main run");
  });
});

describe("SME export", () => {
  it("serves Markdown as a dated attachment", async () => {
    const response = await GET(request("?type=sme"));

    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Disposition")).toMatch(
      /^attachment; filename="esa_sme_targets_\d{4}-\d{2}-\d{2}\.md"$/,
    );
    const body = await response.text();
    expect(body).toContain("# ESA Scout — SME Internship Targets");
    expect(body).toContain("Acme Geospatial SL");
  });

  it("answers 404 with the SME command when nothing has been scanned", async () => {
    loadSmeSnapshot.mockResolvedValue({
      snapshot: EMPTY_SME_SNAPSHOT,
      sourcePath: null,
      error: "No sme_matches.json found.",
    });

    const response = await GET(request("?type=sme"));
    const payload = await response.json();

    expect(response.status).toBe(404);
    expect(payload.hint).toContain("sme --evaluate");
  });
});

describe("unknown type", () => {
  it("is rejected as a 400 rather than silently exporting opportunities", async () => {
    const response = await GET(request("?type=everything"));
    const payload = await response.json();

    expect(response.status).toBe(400);
    expect(payload.expected).toEqual(["opportunities", "sme"]);
    expect(loadSnapshot).not.toHaveBeenCalled();
    expect(loadSmeSnapshot).not.toHaveBeenCalled();
  });
});
