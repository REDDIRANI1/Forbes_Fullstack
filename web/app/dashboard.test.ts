import assert from "node:assert/strict";
import test from "node:test";

import {
  DASHBOARD_REFRESH_MS,
  isValidCombination,
  nextValidSelection,
  preferredChartSelection,
  sortRates,
  typesForProvider,
  uniqueProviders,
  type Rate,
  type RateOption,
} from "./dashboard.ts";

const options: RateOption[] = [
  { provider_name: "alpha", rate_type: "fixed" },
  { provider_name: "alpha", rate_type: "variable" },
  { provider_name: "bravo", rate_type: "fixed" },
];

const seededOptions: RateOption[] = [
  { provider_name: "alpha", rate_type: "fixed" },
  { provider_name: "bank of america", rate_type: "15yr_fixed_mortgage" },
  { provider_name: "bank of america", rate_type: "savings_easy_access" },
  { provider_name: "chase", rate_type: "savings_easy_access" },
];

test("dashboard refreshes on a 60 second interval", () => {
  assert.equal(DASHBOARD_REFRESH_MS, 60_000);
});

test("provider and rate type selectors use valid combinations", () => {
  assert.deepEqual(uniqueProviders(options), ["alpha", "bravo"]);
  assert.deepEqual(typesForProvider(options, "alpha"), ["fixed", "variable"]);
  assert.equal(isValidCombination(options, "alpha", "variable"), true);
  assert.equal(isValidCombination(options, "bravo", "variable"), false);
  assert.deepEqual(nextValidSelection(options, "bravo", "variable"), {
    provider: "bravo",
    rateType: "fixed",
  });
  assert.deepEqual(nextValidSelection(options, "", ""), {
    provider: "alpha",
    rateType: "fixed",
  });
});

test("initial selection prefers a dense 30-day chart pair when available", () => {
  assert.deepEqual(preferredChartSelection(seededOptions), {
    provider: "bank of america",
    rateType: "savings_easy_access",
  });
  assert.deepEqual(nextValidSelection(seededOptions, "", ""), {
    provider: "bank of america",
    rateType: "savings_easy_access",
  });
  assert.deepEqual(nextValidSelection(seededOptions, "chase", "savings_easy_access"), {
    provider: "chase",
    rateType: "savings_easy_access",
  });
});

test("latest table sorting stays stable for rate value and update date", () => {
  const rates: Rate[] = [
    {
      id: 1,
      provider_name: "alpha",
      rate_type: "fixed",
      rate_value: "5.0000",
      effective_date: "2025-01-02",
      ingested_at: "2025-01-02T00:00:00Z",
    },
    {
      id: 2,
      provider_name: "bravo",
      rate_type: "fixed",
      rate_value: "3.0000",
      effective_date: "2025-01-03",
      ingested_at: "2025-01-03T00:00:00Z",
    },
  ];
  assert.deepEqual(
    sortRates(rates, "rate_value", false).map((rate) => rate.provider_name),
    ["bravo", "alpha"],
  );
  assert.deepEqual(
    sortRates(rates, "effective_date", true).map((rate) => rate.provider_name),
    ["bravo", "alpha"],
  );
});
