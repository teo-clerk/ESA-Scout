import { describe, expect, it } from "vitest";

import {
  applyFilters,
  INITIAL_FILTERS,
  isFiltered,
  sortOpportunities,
} from "@/lib/filter";

import { makeEvaluation, makeOpportunity } from "./factories";

const filters = (overrides = {}) => ({ ...INITIAL_FILTERS, ...overrides });

describe("applyFilters", () => {
  const dataset = [
    makeOpportunity({
      id: "a",
      title: "Earth Observation Course",
      status: "Open",
      category: "Earth Observation & AI",
      match_score: 90,
      deadline: "2026-10-01",
    }),
    makeOpportunity({
      id: "b",
      title: "CubeSat Workshop",
      status: "Pending",
      category: "Space Systems",
      match_score: 60,
      deadline: "2026-09-01",
    }),
    makeOpportunity({
      id: "c",
      title: "Robotics Summer School",
      status: "Closed",
      category: "Robotics & Software",
      match_score: 75,
      deadline: "",
    }),
  ];

  it("returns everything by default", () => {
    expect(applyFilters(dataset, filters())).toHaveLength(3);
  });

  it("filters by status", () => {
    const result = applyFilters(dataset, filters({ status: "Open" }));
    expect(result.map((o) => o.id)).toEqual(["a"]);
  });

  it("filters by category", () => {
    const result = applyFilters(dataset, filters({ category: "Space Systems" }));
    expect(result.map((o) => o.id)).toEqual(["b"]);
  });

  it("searches titles case-insensitively", () => {
    expect(applyFilters(dataset, filters({ query: "cubesat" }))).toHaveLength(1);
    expect(applyFilters(dataset, filters({ query: "CUBESAT" }))).toHaveLength(1);
  });

  it("ignores surrounding whitespace in the query", () => {
    expect(applyFilters(dataset, filters({ query: "  robotics  " }))).toHaveLength(1);
  });

  it("searches AI-derived required skills", () => {
    const withSkills = [
      makeOpportunity({
        id: "x",
        title: "Unrelated Title",
        evaluation: makeEvaluation({ required_skills: ["Python", "SAR imaging"] }),
      }),
    ];
    expect(applyFilters(withSkills, filters({ query: "python" }))).toHaveLength(1);
  });

  it("combines filters conjunctively", () => {
    const result = applyFilters(
      dataset,
      filters({ status: "Open", category: "Space Systems" }),
    );
    expect(result).toHaveLength(0);
  });

  it("returns an empty array when nothing matches", () => {
    expect(applyFilters(dataset, filters({ query: "quantum" }))).toEqual([]);
  });

  it("does not mutate the input array", () => {
    const input = [...dataset];
    applyFilters(input, filters({ sort: "title" }));
    expect(input.map((o) => o.id)).toEqual(["a", "b", "c"]);
  });
});

describe("sortOpportunities", () => {
  const dataset = [
    makeOpportunity({ id: "low", title: "Zebra", match_score: 10, deadline: "2026-01-01" }),
    makeOpportunity({ id: "high", title: "Alpha", match_score: 95, deadline: "2026-12-01" }),
    makeOpportunity({ id: "none", title: "Mid", match_score: 50, deadline: "" }),
  ];

  it("sorts by match score descending", () => {
    expect(sortOpportunities(dataset, "match").map((o) => o.id)).toEqual([
      "high",
      "none",
      "low",
    ]);
  });

  it("sorts by deadline ascending", () => {
    expect(sortOpportunities(dataset, "deadline").map((o) => o.id)).toEqual([
      "low",
      "high",
      "none",
    ]);
  });

  it("places undated opportunities last, not first", () => {
    const result = sortOpportunities(dataset, "deadline");
    expect(result[result.length - 1].id).toBe("none");
  });

  it("sorts by title alphabetically", () => {
    expect(sortOpportunities(dataset, "title").map((o) => o.title)).toEqual([
      "Alpha",
      "Mid",
      "Zebra",
    ]);
  });

  it("breaks match-score ties by earliest deadline", () => {
    const tied = [
      makeOpportunity({ id: "later", match_score: 80, deadline: "2026-12-01" }),
      makeOpportunity({ id: "sooner", match_score: 80, deadline: "2026-06-01" }),
    ];
    expect(sortOpportunities(tied, "match").map((o) => o.id)).toEqual([
      "sooner",
      "later",
    ]);
  });

  it("does not mutate its input", () => {
    const input = [...dataset];
    sortOpportunities(input, "title");
    expect(input.map((o) => o.id)).toEqual(["low", "high", "none"]);
  });
});

describe("isFiltered", () => {
  it("is false for the initial state", () => {
    expect(isFiltered(INITIAL_FILTERS)).toBe(false);
  });

  it("ignores the sort order", () => {
    expect(isFiltered(filters({ sort: "title" }))).toBe(false);
  });

  it.each([
    ["query", { query: "x" }],
    ["status", { status: "Open" as const }],
    ["category", { category: "Space Systems" }],
  ])("is true when %s is set", (_label, patch) => {
    expect(isFiltered(filters(patch))).toBe(true);
  });
});
