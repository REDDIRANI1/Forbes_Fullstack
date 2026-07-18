"use client";

import { useEffect, useRef, useState } from "react";

import { DASHBOARD_REFRESH_MS, displayType, isValidCombination, nextValidSelection, sortRates, typesForProvider, uniqueProviders, type Rate, type RateOption, type SortField } from "./dashboard";

type History = { results: Rate[]; next: string | null };
type OptionsResponse = { combinations: RateOption[] };
const api = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export default function Home() {
  const [rates, setRates] = useState<Rate[]>([]);
  const [provider, setProvider] = useState("");
  const [rateType, setRateType] = useState("");
  const [history, setHistory] = useState<Rate[]>([]);
  const [options, setOptions] = useState<RateOption[]>([]);
  const [sort, setSort] = useState<SortField>("rate_value");
  const [descending, setDescending] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const [latestState, setLatestState] = useState("Loading current rates");
  const [historyState, setHistoryState] = useState("Choose a provider and rate type to view history");
  const [optionsState, setOptionsState] = useState("");
  const selectionRef = useRef({ provider: "", rateType: "" });

  useEffect(() => {
    selectionRef.current = { provider, rateType };
  }, [provider, rateType]);

  useEffect(() => {
    const interval = setInterval(() => setRefreshTick((tick) => tick + 1), DASHBOARD_REFRESH_MS);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const latestData: Rate[] = await fetch(`${api}/rates/latest`).then((result) => result.ok ? result.json() : Promise.reject());
        if (!alive) return;
        setRates(latestData);
        setLatestState(latestData.length ? "" : "No current rates are available.");
      } catch {
        if (alive) setLatestState("Current rates could not be loaded. Retry in a moment.");
      }
    };
    load();
    return () => { alive = false; };
  }, [refreshTick]);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const optionsData: OptionsResponse = await fetch(`${api}/rates/options`).then((result) => result.ok ? result.json() : Promise.reject());
        if (!alive) return;
        const combinations = optionsData.combinations || [];
        const selected = nextValidSelection(combinations, selectionRef.current.provider, selectionRef.current.rateType);
        setOptions(combinations);
        setProvider(selected.provider);
        setRateType(selected.rateType);
        setOptionsState("");
      } catch {
        if (alive) setOptionsState("Provider/type options could not be loaded. Retry in a moment.");
      }
    };
    load();
    return () => { alive = false; };
  }, [refreshTick]);

  useEffect(() => {
    if (!provider || !rateType || (options.length > 0 && !isValidCombination(options, provider, rateType))) return;
    let alive = true;
    const load = async () => {
      await Promise.resolve();
      if (alive) setHistoryState("Loading 30-day history");
      try {
        const latestByType: Rate[] = await fetch(`${api}/rates/latest?type=${encodeURIComponent(rateType)}`).then((result) => result.ok ? result.json() : Promise.reject());
        const latest = latestByType.find((rate) => rate.provider_name === provider);
        if (!latest) throw new Error("No matching rate");
        const from = new Date(latest.effective_date);
        from.setDate(from.getDate() - 30);
        let url: string | null = `${api}/rates/history?provider=${encodeURIComponent(provider)}&type=${encodeURIComponent(rateType)}&from=${from.toISOString().slice(0, 10)}&to=${latest.effective_date}&page_size=100`;
        const allResults: Rate[] = [];
        while (url) {
          const page: History = await fetch(url).then((result) => result.ok ? result.json() : Promise.reject());
          if (!alive) return;
          allResults.push(...page.results);
          url = page.next;
        }
        setHistory(allResults);
        setHistoryState(allResults.length ? "" : "No records were available in this 30-day window.");
      } catch {
        if (alive) setHistoryState("History could not be loaded.");
      }
    };
    load();
    return () => { alive = false; };
  }, [provider, rateType, refreshTick, options]);

  const providers = uniqueProviders(options);
  const rateTypes = typesForProvider(options, provider);
  const ordered = sortRates(rates, sort, descending);
  const values = history.map((rate) => Number(rate.rate_value));
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const pointCoordinates = history.map((rate, index) => ({
    x: history.length < 2 ? 50 : (index / (history.length - 1)) * 100,
    y: 100 - ((Number(rate.rate_value) - minimum) / Math.max(0.01, maximum - minimum)) * 100,
  }));
  const points = pointCoordinates.map((point) => `${point.x},${point.y}`).join(" ");
  const setSortField = (field: SortField) => { setDescending((current) => sort === field ? !current : false); setSort(field); };

  return <main>
    <header><p className="eyebrow">Forbes Advisor assessment</p><h1>Rate tracker</h1><p>Live provider comparison, refreshed every minute.</p></header>
    <section className="table"><div className="section-head"><h2>Latest rate by provider</h2><div><button onClick={() => setSortField("rate_value")}>Sort by value {sort === "rate_value" && (descending ? "▼" : "▲")}</button><button onClick={() => setSortField("effective_date")}>Sort by update {sort === "effective_date" && (descending ? "▼" : "▲")}</button></div></div>{latestState ? <p className="state">{latestState}</p> : <div className="scroll"><table><thead><tr><th>Provider</th><th>Type</th><th className="rate-value">Rate</th><th>Updated</th></tr></thead><tbody>{ordered.map((rate) => <tr key={rate.id} onClick={() => { setProvider(rate.provider_name); setRateType(rate.rate_type); }} className={provider === rate.provider_name && rateType === rate.rate_type ? "selected" : ""}><td>{rate.provider_name}</td><td>{displayType(rate.rate_type)}</td><td className="rate-value">{rate.rate_value}%</td><td>{rate.effective_date}</td></tr>)}</tbody></table></div>}</section>
    <section className="chart"><div><p className="eyebrow">30-day movement</p><h2>Compare a provider and rate type</h2></div><div className="selectors"><label>Provider<select value={provider} onChange={(event) => { const nextProvider = event.target.value; setProvider(nextProvider); setRateType(typesForProvider(options, nextProvider)[0] || ""); }}>{providers.map((value) => <option key={value}>{value}</option>)}</select></label><label>Rate type<select value={rateType} onChange={(event) => setRateType(event.target.value)}>{rateTypes.map((value) => <option key={value} value={value}>{displayType(value)}</option>)}</select></label></div>{optionsState && <p className="state">{optionsState}</p>}{historyState ? <p className="state">{historyState}</p> : <div><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={`${provider} ${rateType} rate history line chart`}>{history.length === 1 ? <circle cx={pointCoordinates[0].x} cy={pointCoordinates[0].y} r="2.5" /> : <polyline points={points} />}</svg>{history.length === 1 ? <p className="state compact">Only one record exists in this 30-day window, so the chart shows a single point.</p> : null}</div>}</section>
  </main>;
}
