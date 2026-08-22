/**
 * Filtering and sorting for the SME target list.
 *
 * With ~300 companies the list is only usable if these are exactly right, so
 * they are tested directly rather than through the component.
 */

import { describe, expect, it } from "vitest";

import {
  applySmeFilters,
  countriesOf,
  domainsOf,
  INITIAL_SME_FILTERS,
  isRanked,
  isSmeFiltered,
  sortSmes,
  type SmeFilterState,
} from "@/lib/sme-filter";
import { makeRankedSme, makeSme, makeSmeEvaluation } from "./factories";

function filters(overrides: Partial<SmeFilterState> = {}): SmeFilterState {
  return { ...INITIAL_SME_FILTERS, ...overrides };
}

describe("applySmeFilters", () => {
  it("returns everything by default", () => {
    const companies = [makeSme({ id: "a" }), makeSme({ id: "b" })];
    expect(applySmeFilters(companies, filters())).toHaveLength(2);
  });

  it("filters by country code", () => {
    const companies = [
      makeSme({ id: "es", country_code: "ES" }),
      makeSme({ id: "it", country_code: "IT" }),
    ];
    const result = applySmeFilters(companies, filters({ country: "IT" }));
    expect(result.map((c) => c.id)).toEqual(["it"]);
  });

  it("filters by a derived domain tag", () => {
    const companies = [
      makeSme({ id: "eo", domains: ["Earth Observation"] }),
      makeSme({ id: "sw", domains: ["Software"] }),
    ];
    const result = applySmeFilters(companies, filters({ domain: "Software" }));
    expect(result.map((c) => c.id)).toEqual(["sw"]);
  });

  it("requires an exact domain match, not a substring", () => {
    const companies = [makeSme({ domains: ["Remote Sensing"] })];
    expect(applySmeFilters(companies, filters({ domain: "Sensing" }))).toEqual([]);
  });

  it("combines country and domain filters", () => {
    const companies = [
      makeSme({ id: "a", country_code: "ES", domains: ["GIS"] }),
      makeSme({ id: "b", country_code: "IT", domains: ["GIS"] }),
      makeSme({ id: "c", country_code: "IT", domains: ["Software"] }),
    ];
    const result = applySmeFilters(
      companies,
      filters({ country: "IT", domain: "GIS" }),
    );
    expect(result.map((c) => c.id)).toEqual(["b"]);
  });

  it("searches name, city and description case-insensitively", () => {
    const companies = [
      makeSme({ id: "a", name: "Orbital Insight", description: "" }),
      makeSme({ id: "b", name: "Other", city: "Torino", description: "" }),
      makeSme({ id: "c", name: "Third", description: "SAR interferometry" }),
    ];
    expect(applySmeFilters(companies, filters({ query: "ORBITAL" }))[0].id).toBe("a");
    expect(applySmeFilters(companies, filters({ query: "torino" }))[0].id).toBe("b");
    expect(applySmeFilters(companies, filters({ query: "sar" }))[0].id).toBe("c");
  });

  it("searches the AI-suggested role too", () => {
    const companies = [
      makeSme({
        id: "a",
        name: "Nondescript SL",
        description: "",
        evaluation: makeSmeEvaluation({ suggested_role: "Computer vision intern" }),
      }),
    ];
    expect(applySmeFilters(companies, filters({ query: "vision" }))).toHaveLength(1);
  });

  it("ignores surrounding whitespace in the query", () => {
    const companies = [makeSme({ name: "Acme Geospatial SL" })];
    expect(applySmeFilters(companies, filters({ query: "  acme  " }))).toHaveLength(1);
  });

  it("hides unranked companies when rankedOnly is set", () => {
    const companies = [
      makeRankedSme(80, { id: "ranked" }),
      makeSme({ id: "unranked", evaluation: null }),
    ];
    const result = applySmeFilters(companies, filters({ rankedOnly: true }));
    expect(result.map((c) => c.id)).toEqual(["ranked"]);
  });

  it("treats a failed evaluation as unranked", () => {
    const failed = makeSme({
      id: "failed",
      evaluation: makeSmeEvaluation({ error: "timeout" }),
    });
    expect(isRanked(failed)).toBe(false);
    expect(applySmeFilters([failed], filters({ rankedOnly: true }))).toEqual([]);
  });

  it("does not mutate the array it is given", () => {
    const companies = [makeRankedSme(10, { id: "a" }), makeRankedSme(90, { id: "b" })];
    const order = companies.map((c) => c.id);
    applySmeFilters(companies, filters());
    expect(companies.map((c) => c.id)).toEqual(order);
  });
});

describe("sortSmes", () => {
  it("orders by fit score descending by default", () => {
    const companies = [
      makeRankedSme(40, { id: "mid" }),
      makeRankedSme(95, { id: "top" }),
      makeRankedSme(10, { id: "low" }),
    ];
    expect(sortSmes(companies, "fit").map((c) => c.id)).toEqual([
      "top",
      "mid",
      "low",
    ]);
  });

  it("breaks fit ties by name so ordering is stable", () => {
    const companies = [
      makeRankedSme(80, { id: "b", name: "Beta" }),
      makeRankedSme(80, { id: "a", name: "Alpha" }),
    ];
    expect(sortSmes(companies, "fit").map((c) => c.id)).toEqual(["a", "b"]);
  });

  it("sorts unranked companies last", () => {
    const companies = [
      makeSme({ id: "unranked", evaluation: null, fit_score: 0 }),
      makeRankedSme(30, { id: "ranked" }),
    ];
    expect(sortSmes(companies, "fit")[0].id).toBe("ranked");
  });

  it("sorts by name alphabetically", () => {
    const companies = [
      makeSme({ id: "z", name: "Zeta" }),
      makeSme({ id: "a", name: "Alpha" }),
    ];
    expect(sortSmes(companies, "name").map((c) => c.id)).toEqual(["a", "z"]);
  });

  it("sorts by domain breadth, then fit", () => {
    const companies = [
      makeRankedSme(90, { id: "narrow", domains: ["GIS"] }),
      makeRankedSme(10, { id: "broad", domains: ["GIS", "Software", "AI"] }),
    ];
    expect(sortSmes(companies, "domains").map((c) => c.id)).toEqual([
      "broad",
      "narrow",
    ]);
  });
});

describe("domainsOf", () => {
  it("collects a deduplicated, alphabetical list", () => {
    const companies = [
      makeSme({ domains: ["Software", "GIS"] }),
      makeSme({ domains: ["GIS", "Earth Observation"] }),
    ];
    expect(domainsOf(companies)).toEqual(["Earth Observation", "GIS", "Software"]);
  });

  it("is empty when nothing has domains", () => {
    expect(domainsOf([makeSme({ domains: [] })])).toEqual([]);
  });
});

describe("countriesOf", () => {
  it("preserves first-seen order and drops blanks", () => {
    const companies = [
      makeSme({ country_code: "IT" }),
      makeSme({ country_code: "ES" }),
      makeSme({ country_code: "IT" }),
      makeSme({ country_code: "" }),
    ];
    expect(countriesOf(companies)).toEqual(["IT", "ES"]);
  });
});

describe("isSmeFiltered", () => {
  it("is false for the initial state", () => {
    expect(isSmeFiltered(INITIAL_SME_FILTERS)).toBe(false);
  });

  it.each([
    ["query", { query: "a" }],
    ["country", { country: "ES" }],
    ["domain", { domain: "GIS" }],
    ["rankedOnly", { rankedOnly: true }],
  ])("is true once %s is set", (_label, overrides) => {
    expect(isSmeFiltered(filters(overrides))).toBe(true);
  });

  it("ignores the sort key, which is not a filter", () => {
    expect(isSmeFiltered(filters({ sort: "name" }))).toBe(false);
  });
});
