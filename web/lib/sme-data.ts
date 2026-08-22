/**
 * Server-side loader for `data/sme_matches.json`.
 *
 * Mirrors `lib/data.ts`: production reads the copy inside the Next.js project
 * (the only one guaranteed to ship to Vercel), while development prefers the
 * repository root so a local `python -m agent.main sme` shows up immediately.
 */

import { promises as fs } from "node:fs";
import path from "node:path";

import { EMPTY_SME_SNAPSHOT, type SmeSnapshot } from "./sme-types";

export const SME_DATA_FILENAME = "sme_matches.json";

/** Production source: statically scoped inside the Next.js project. */
const MIRROR_PATH = path.join(process.cwd(), "public", "data", SME_DATA_FILENAME);

export interface SmeLoadResult {
  snapshot: SmeSnapshot;
  sourcePath: string | null;
  error: string | null;
}

async function readIfPresent(filePath: string): Promise<string | null> {
  try {
    return await fs.readFile(filePath, "utf-8");
  } catch {
    return null;
  }
}

/**
 * Read the SME snapshot. Never throws: a missing or corrupt file yields an
 * empty snapshot plus an error message, so the page explains itself instead of
 * returning a 500.
 */
export async function loadSmeSnapshot(): Promise<SmeLoadResult> {
  const attempted: string[] = [];

  if (process.env.NODE_ENV !== "production") {
    const devPath = path.join(process.cwd(), "..", "data", SME_DATA_FILENAME);
    attempted.push(devPath);
    const devRaw = await readIfPresent(/* turbopackIgnore: true */ devPath);
    if (devRaw !== null) return parse(devRaw, devPath);
  }

  attempted.push(MIRROR_PATH);
  const raw = await readIfPresent(MIRROR_PATH);
  if (raw !== null) return parse(raw, MIRROR_PATH);

  return {
    snapshot: EMPTY_SME_SNAPSHOT,
    sourcePath: null,
    error:
      `No ${SME_DATA_FILENAME} found. Run \`python -m agent.main sme --evaluate\` ` +
      `to generate it. Looked in: ${attempted.join(", ")}`,
  };
}

function parse(raw: string, sourcePath: string): SmeLoadResult {
  try {
    return {
      snapshot: normalise(JSON.parse(raw) as Partial<SmeSnapshot>),
      sourcePath,
      error: null,
    };
  } catch (cause) {
    return {
      snapshot: EMPTY_SME_SNAPSHOT,
      sourcePath,
      error: `Could not parse ${sourcePath}: ${(cause as Error).message}`,
    };
  }
}

/** Fill in any field an older or partial file might be missing. */
function normalise(parsed: Partial<SmeSnapshot>): SmeSnapshot {
  return {
    ...EMPTY_SME_SNAPSHOT,
    ...parsed,
    stats: { ...EMPTY_SME_SNAPSHOT.stats, ...(parsed.stats ?? {}) },
    companies: parsed.companies ?? [],
    countries: parsed.countries ?? [],
    keywords: parsed.keywords ?? [],
    errors: parsed.errors ?? [],
  };
}
