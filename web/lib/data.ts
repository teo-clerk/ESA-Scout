/**
 * Server-side loader for the agent's output.
 *
 * The canonical file is `data/opportunities.json` at the repository root. The
 * agent mirrors it to `web/public/data/opportunities.json` on every run,
 * because only files inside the Next.js project are guaranteed to ship in a
 * Vercel deployment — that mirror is the single production source.
 *
 * The repository-root path is consulted in development only. Keeping it behind
 * a `NODE_ENV` check matters: a dynamic, unscoped `fs` path makes Next.js trace
 * the entire project into the serverless bundle, which bloats deployments.
 */

import { promises as fs } from "node:fs";
import path from "node:path";

import { EMPTY_SNAPSHOT, type Snapshot } from "./types";

export const DATA_FILENAME = "opportunities.json";

/** Production source: statically scoped inside the Next.js project. */
const MIRROR_PATH = path.join(process.cwd(), "public", "data", DATA_FILENAME);

export interface LoadResult {
  snapshot: Snapshot;
  /** Path the data came from, or null when nothing was found. */
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
 * Read the snapshot, preferring the freshest available copy.
 *
 * Never throws: a missing or corrupt file yields an empty snapshot plus an
 * error message, so the dashboard renders an explanatory empty state rather
 * than a 500.
 */
export async function loadSnapshot(): Promise<LoadResult> {
  const attempted: string[] = [];

  // In development the repository root is authoritative, so edits from a local
  // agent run show up without waiting for the mirror.
  if (process.env.NODE_ENV !== "production") {
    const devPath = path.join(process.cwd(), "..", "data", DATA_FILENAME);
    attempted.push(devPath);
    const devRaw = await readIfPresent(/* turbopackIgnore: true */ devPath);
    if (devRaw !== null) return parseSnapshot(devRaw, devPath);
  }

  attempted.push(MIRROR_PATH);
  const raw = await readIfPresent(MIRROR_PATH);
  if (raw !== null) return parseSnapshot(raw, MIRROR_PATH);

  return {
    snapshot: EMPTY_SNAPSHOT,
    sourcePath: null,
    error:
      `No ${DATA_FILENAME} found. Run \`python -m agent.main run\` to generate it. ` +
      `Looked in: ${attempted.join(", ")}`,
  };
}

function parseSnapshot(raw: string, sourcePath: string): LoadResult {
  try {
    return {
      snapshot: normalise(JSON.parse(raw) as Partial<Snapshot>),
      sourcePath,
      error: null,
    };
  } catch (cause) {
    // Found but unreadable: report it rather than silently falling through to a
    // stale copy, which would hide the corruption.
    return {
      snapshot: EMPTY_SNAPSHOT,
      sourcePath,
      error: `Could not parse ${sourcePath}: ${(cause as Error).message}`,
    };
  }
}

/** Fill in any field an older or partial file might be missing. */
function normalise(parsed: Partial<Snapshot>): Snapshot {
  return {
    ...EMPTY_SNAPSHOT,
    ...parsed,
    stats: { ...EMPTY_SNAPSHOT.stats, ...(parsed.stats ?? {}) },
    profile: {
      ...EMPTY_SNAPSHOT.profile,
      ...(parsed.profile ?? {}),
      github: {
        ...EMPTY_SNAPSHOT.profile.github,
        ...(parsed.profile?.github ?? {}),
      },
    },
    opportunities: parsed.opportunities ?? [],
    events: parsed.events ?? [],
    errors: parsed.errors ?? [],
  };
}
