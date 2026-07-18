"use client";

import { useEffect, useState } from "react";

type Rate = { id: number; provider_name: string; rate_type: string; rate_value: string; effective_date: string; ingested_at: string };
type History = { results: Rate[] };
type SortField = "rate_value" | "effective_date";
const api = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

function displayType(value: string) { return value.replaceAll("_", " "); }

export default function Home() {
  const [rates, setRates] = useState<Rate[]>([]);
  const [provider, setProvider] = useState("");
  const [rateType, setRateType] = useState("");
  const [history, setHistory] = useState<Rate[]>([]);
  const [sort, setSort] = useState<SortField>("rate_value");
  const [descending, setDescending] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const [latestState, setLatestState] = useState("Loading current rates");
  const [historyState, setHistoryState] = useState("Choose a provider and rate type to view history");

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const data: Rate[] = await fetch(`${api}/rates/latest`).then((result) => result.ok ? result.json() : Promise.reject());
        if (!alive) return;
        setRates(data);
        setProvider((current) => current || data[0]?.provider_name || "");
        setRateType((current) => current || data[0]?.rate_type || "");
        setLatestState(data.length ? "" : "No current rates are available.");
      } catch {
        if (alive) setLatestState("Current rates could not be loaded. Retry in a moment.");
      }
    };
    load();
    const interval = setInterval(() => setRefreshTick((tick) => tick + 1), 60_000);
    return () => { alive = false; clearInterval(interval); };
  }, []);

  useEffect(() => {
    if (!provider || !rateType) return;
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
        const data: History = await fetch(`${api}/rates/history?provider=${encodeURIComponent(provider)}&type=${encodeURIComponent(rateType)}&from=${from.toISOString().slice(0, 10)}&to=${latest.effective_date}&page_size=100`).then((result) => result.ok ? result.json() : Promise.reject());
        if (!alive) return;
        setHistory(data.results);
        setHistoryState(data.results.length ? "" : "No records were available in this 30-day window.");
      } catch {
        if (alive) setHistoryState("History could not be loaded.");
      }
    };
    load();
    return () => { alive = false; };
  }, [provider, rateType, refreshTick]);

  const providers = [...new Set(rates.map((rate) => rate.provider_name))].sort();
  const rateTypes = [...new Set(rates.map((rate) => rate.rate_type))].sort();
  const ordered = [...rates].sort((left, right) => {
    const compared = sort === "rate_value" ? Number(left.rate_value) - Number(right.rate_value) : left.effective_date.localeCompare(right.effective_date);
    return descending ? -compared : compared;
  });
  const values = history.map((rate) => Number(rate.rate_value));
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const points = history.map((rate, index) => `${history.length < 2 ? 50 : (index / (history.length - 1)) * 100},${100 - ((Number(rate.rate_value) - minimum) / Math.max(0.01, maximum - minimum)) * 100}`).join(" ");
  const setSortField = (field: SortField) => { setDescending((current) => sort === field ? !current : false); setSort(field); };

  return <main>
    <header><p className="eyebrow">Forbes Advisor assessment</p><h1>Rate tracker</h1><p>Live provider comparison, refreshed every minute.</p></header>
    <section className="table"><div className="section-head"><h2>Latest rate by provider</h2><div><button onClick={() => setSortField("rate_value")}>Sort by value {sort === "rate_value" && (descending ? "▼" : "▲")}</button><button onClick={() => setSortField("effective_date")}>Sort by update {sort === "effective_date" && (descending ? "▼" : "▲")}</button></div></div>{latestState ? <p className="state">{latestState}</p> : <div className="scroll"><table><thead><tr><th>Provider</th><th>Type</th><th className="rate-value">Rate</th><th>Updated</th></tr></thead><tbody>{ordered.map((rate) => <tr key={rate.id} onClick={() => { setProvider(rate.provider_name); setRateType(rate.rate_type); }} className={provider === rate.provider_name && rateType === rate.rate_type ? "selected" : ""}><td>{rate.provider_name}</td><td>{displayType(rate.rate_type)}</td><td className="rate-value">{rate.rate_value}%</td><td>{rate.effective_date}</td></tr>)}</tbody></table></div>}</section>
    <section className="chart"><div><p className="eyebrow">30-day movement</p><h2>Compare a provider and rate type</h2></div><div className="selectors"><label>Provider<select value={provider} onChange={(event) => setProvider(event.target.value)}>{providers.map((value) => <option key={value}>{value}</option>)}</select></label><label>Rate type<select value={rateType} onChange={(event) => setRateType(event.target.value)}>{rateTypes.map((value) => <option key={value} value={value}>{displayType(value)}</option>)}</select></label></div>{historyState ? <p className="state">{historyState}</p> : <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={`${provider} ${rateType} rate history line chart`}><polyline points={points} /></svg>}</section>
  </main>;
}
