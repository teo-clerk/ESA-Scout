import { describe, expect, it } from "vitest";

import {
  categoriesOf,
  daysUntil,
  deadlineInfo,
  formatDate,
  isStale,
  matchTone,
  parseIsoDate,
  relativeTime,
} from "@/lib/format";

import { makeOpportunity } from "./factories";

const NOW = new Date("2026-08-17T12:00:00Z");

describe("parseIsoDate", () => {
  it("parses an ISO date as UTC", () => {
    expect(parseIsoDate("2026-04-05")?.toISOString()).toBe("2026-04-05T00:00:00.000Z");
  });

  it("accepts a full timestamp", () => {
    expect(parseIsoDate("2026-04-05T13:00:00Z")?.getUTCDate()).toBe(5);
  });

  it.each(["", "not a date", "05/04/2026"])("rejects %j", (value) => {
    expect(parseIsoDate(value)).toBeNull();
  });
});

describe("daysUntil", () => {
  it("counts forward", () => {
    expect(daysUntil("2026-08-20", NOW)).toBe(3);
  });

  it("is zero on the day itself", () => {
    expect(daysUntil("2026-08-17", NOW)).toBe(0);
  });

  it("is negative once past", () => {
    expect(daysUntil("2026-08-10", NOW)).toBe(-7);
  });

  it("is null without a date", () => {
    expect(daysUntil("", NOW)).toBeNull();
  });
});

describe("deadlineInfo", () => {
  it("marks a deadline inside a week as urgent", () => {
    const info = deadlineInfo(makeOpportunity({ deadline: "2026-08-20" }), NOW);
    expect(info.tone).toBe("urgent");
    expect(info.label).toBe("3 days left");
  });

  it("uses the singular for one day", () => {
    expect(deadlineInfo(makeOpportunity({ deadline: "2026-08-18" }), NOW).label).toBe(
      "1 day left",
    );
  });

  it("names today explicitly", () => {
    expect(deadlineInfo(makeOpportunity({ deadline: "2026-08-17" }), NOW).label).toBe(
      "Deadline today",
    );
  });

  it("marks three weeks out as soon", () => {
    expect(deadlineInfo(makeOpportunity({ deadline: "2026-09-01" }), NOW).tone).toBe(
      "soon",
    );
  });

  it("marks a far deadline as distant", () => {
    expect(deadlineInfo(makeOpportunity({ deadline: "2027-01-01" }), NOW).tone).toBe(
      "distant",
    );
  });

  it("reports an elapsed deadline rather than hiding it", () => {
    const info = deadlineInfo(makeOpportunity({ deadline: "2026-08-10" }), NOW);
    expect(info.tone).toBe("passed");
    expect(info.label).toBe("Deadline passed 7 days ago");
  });

  it("falls back to the published wording when there is no ISO date", () => {
    const info = deadlineInfo(
      makeOpportunity({ deadline: "", deadline_text: "Rolling call" }),
      NOW,
    );
    expect(info.tone).toBe("none");
    expect(info.label).toBe("Rolling call");
  });

  it("says so when nothing is listed at all", () => {
    const info = deadlineInfo(makeOpportunity({ deadline: "", deadline_text: "" }), NOW);
    expect(info.label).toBe("No deadline listed");
  });
});

describe("formatDate", () => {
  it("renders a readable date", () => {
    expect(formatDate("2026-04-05")).toBe("5 April 2026");
  });

  it("uses the fallback for an unparseable value", () => {
    expect(formatDate("", "19 April")).toBe("19 April");
  });
});

describe("relativeTime", () => {
  it.each([
    ["2026-08-17T11:59:30Z", "just now"],
    ["2026-08-17T11:30:00Z", "30 minutes ago"],
    ["2026-08-17T09:00:00Z", "3 hours ago"],
    ["2026-08-15T12:00:00Z", "2 days ago"],
  ])("renders %s as %s", (iso, expected) => {
    expect(relativeTime(iso, NOW)).toBe(expected);
  });

  it("handles a missing timestamp", () => {
    expect(relativeTime("", NOW)).toBe("never");
  });

  it("handles an invalid timestamp", () => {
    expect(relativeTime("garbage", NOW)).toBe("unknown");
  });
});

describe("isStale", () => {
  it("is false for a recent sync", () => {
    expect(isStale("2026-08-17T06:00:00Z", NOW)).toBe(false);
  });

  it("is true once past the window", () => {
    expect(isStale("2026-08-15T06:00:00Z", NOW)).toBe(true);
  });

  it("treats a missing timestamp as stale", () => {
    expect(isStale("", NOW)).toBe(true);
  });
});

describe("matchTone", () => {
  it.each([
    [90, "emerald"],
    [70, "sky"],
    [50, "amber"],
    [10, "slate-500"],
    [0, "slate-700"],
  ])("maps %i to a %s bar", (score, fragment) => {
    expect(matchTone(score).bar).toContain(fragment);
  });
});

describe("categoriesOf", () => {
  it("returns unique categories in alphabetical order", () => {
    const list = [
      makeOpportunity({ id: "1", category: "Space Systems" }),
      makeOpportunity({ id: "2", category: "Earth Observation & AI" }),
      makeOpportunity({ id: "3", category: "Space Systems" }),
    ];
    expect(categoriesOf(list)).toEqual(["Earth Observation & AI", "Space Systems"]);
  });

  it("skips empty categories", () => {
    expect(categoriesOf([makeOpportunity({ category: "" })])).toEqual([]);
  });
});
