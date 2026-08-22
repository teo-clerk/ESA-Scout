/** The country-flag helper backing the ES/IT badge on every SME card. */

import { describe, expect, it } from "vitest";

import { countryFlag, EMPTY_SME_SNAPSHOT } from "@/lib/sme-types";

describe("countryFlag", () => {
  it("maps the two supported countries", () => {
    expect(countryFlag("ES")).toBe("🇪🇸");
    expect(countryFlag("IT")).toBe("🇮🇹");
  });

  it("accepts lower-case codes", () => {
    expect(countryFlag("es")).toBe("🇪🇸");
  });

  it("returns an empty string for anything else, never a broken glyph", () => {
    expect(countryFlag("XX")).toBe("");
    expect(countryFlag("")).toBe("");
  });
});

describe("EMPTY_SME_SNAPSHOT", () => {
  it("renders safely before the first scan", () => {
    expect(EMPTY_SME_SNAPSHOT.companies).toEqual([]);
    expect(EMPTY_SME_SNAPSHOT.evaluated).toBe(false);
    expect(EMPTY_SME_SNAPSHOT.stats.matched).toBe(0);
  });
});
