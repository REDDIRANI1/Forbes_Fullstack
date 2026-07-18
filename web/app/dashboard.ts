export type Rate = { id: number; provider_name: string; rate_type: string; rate_value: string; effective_date: string; ingested_at: string };
export type RateOption = { provider_name: string; rate_type: string };
export type SortField = "rate_value" | "effective_date";
export const DASHBOARD_REFRESH_MS = 60_000;

/** Seed pairs known to have multi-point 30-day windows; first match in options wins. */
export const PREFERRED_CHART_SELECTIONS: ReadonlyArray<{ provider: string; rateType: string }> = [
  { provider: "bank of america", rateType: "savings_easy_access" },
  { provider: "wells fargo", rateType: "savings_easy_access" },
  { provider: "chase", rateType: "savings_easy_access" },
  { provider: "citibank", rateType: "savings_easy_access" },
];

export function displayType(value: string) {
  return value.replaceAll("_", " ");
}

export function uniqueProviders(options: RateOption[]) {
  return [...new Set(options.map((option) => option.provider_name))].sort();
}

export function typesForProvider(options: RateOption[], provider: string) {
  return [...new Set(options.filter((option) => option.provider_name === provider).map((option) => option.rate_type))].sort();
}

export function isValidCombination(options: RateOption[], provider: string, rateType: string) {
  return options.some((option) => option.provider_name === provider && option.rate_type === rateType);
}

export function preferredChartSelection(options: RateOption[]) {
  for (const candidate of PREFERRED_CHART_SELECTIONS) {
    if (isValidCombination(options, candidate.provider, candidate.rateType)) {
      return { provider: candidate.provider, rateType: candidate.rateType };
    }
  }
  const provider = uniqueProviders(options)[0] || "";
  return { provider, rateType: typesForProvider(options, provider)[0] || "" };
}

export function nextValidSelection(options: RateOption[], provider: string, rateType: string) {
  if (isValidCombination(options, provider, rateType)) return { provider, rateType };
  if (!provider && !rateType) return preferredChartSelection(options);
  const fallbackProvider = provider && typesForProvider(options, provider).length ? provider : uniqueProviders(options)[0] || "";
  return { provider: fallbackProvider, rateType: typesForProvider(options, fallbackProvider)[0] || "" };
}

export function sortRates(rates: Rate[], sort: SortField, descending: boolean) {
  return [...rates].sort((left, right) => {
    const compared = sort === "rate_value" ? Number(left.rate_value) - Number(right.rate_value) : left.effective_date.localeCompare(right.effective_date);
    return descending ? -compared : compared;
  });
}
