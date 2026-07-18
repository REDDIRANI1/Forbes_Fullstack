export type Rate = { id: number; provider_name: string; rate_type: string; rate_value: string; effective_date: string; ingested_at: string };
export type RateOption = { provider_name: string; rate_type: string };
export type SortField = "rate_value" | "effective_date";
export const DASHBOARD_REFRESH_MS = 60_000;

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

export function nextValidSelection(options: RateOption[], provider: string, rateType: string) {
  if (isValidCombination(options, provider, rateType)) return { provider, rateType };
  const fallbackProvider = provider && typesForProvider(options, provider).length ? provider : uniqueProviders(options)[0] || "";
  return { provider: fallbackProvider, rateType: typesForProvider(options, fallbackProvider)[0] || "" };
}

export function sortRates(rates: Rate[], sort: SortField, descending: boolean) {
  return [...rates].sort((left, right) => {
    const compared = sort === "rate_value" ? Number(left.rate_value) - Number(right.rate_value) : left.effective_date.localeCompare(right.effective_date);
    return descending ? -compared : compared;
  });
}
