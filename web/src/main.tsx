import { useEffect, useMemo, useState } from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip } from "recharts";
import { Activity, ArrowDownRight, ArrowUpRight, Bot, Database, ExternalLink, Network, Play, RefreshCw, Search, Sparkles } from "lucide-react";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { cn } from "./lib/utils";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";
type Overview = { as_of_date: string | null; bar_count: number; relationship_count: number; latest_brief: { headline: string; body: string; evidence: Record<string, unknown>; as_of_date: string } | null; runs: { id: string; type: string; status: string; started_at: string }[] };
type Sector = { symbol: string; as_of: string; close: number; return_5d: number };
type Edge = { leader: string; follower: string; lag_days: number; correlation: number; sample_size: number; window_start: string; window_end: string };
type Stock = { symbol: string; name: string; sector: string; close: number; return_5d: number };
type EventLink = { leader: string; follower: string; title: string; url: string; domain: string; seen_at: string };
type LatencyMetrics = { total_ms: number; p50_ms: number; p95_ms: number };
type ResearchMetrics = { model_calls: number; tool_calls: number; guard_rejections: number; failed_steps: number; model_latency_ms: number; tool_latency_ms: number; model_latency: LatencyMetrics; tool_latency: LatencyMetrics; prompt_tokens: number; completion_tokens: number; quality: { evidence_count: number; citation_count: number; observed_event_source_count: number; cited_event_source_count: number; grounded: boolean; has_risk_disclaimer: boolean } | null };

const sampleTrend = Array.from({ length: 30 }, (_, index) => ({ x: index, value: 84 + Math.sin(index / 4) * 5 + index * .38 + (index % 5 - 2) * 1.2 }));

function App() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [sectors, setSectors] = useState<Sector[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [eventLinks, setEventLinks] = useState<EventLink[]>([]);
  const [question, setQuestion] = useState("Which sectors historically tend to lead other sectors?");
  const [answer, setAnswer] = useState<string | null>(null);
  const [researchMetrics, setResearchMetrics] = useState<ResearchMetrics | null>(null);
  const [loading, setLoading] = useState(false);
  const [pipelineState, setPipelineState] = useState<string | null>(null);

  const load = async () => {
    try {
      const [overviewResponse, sectorsResponse, edgesResponse, stocksResponse, eventLinksResponse] = await Promise.all([fetch(`${API}/api/overview`), fetch(`${API}/api/sectors`), fetch(`${API}/api/relationships`), fetch(`${API}/api/stocks`), fetch(`${API}/api/event-links`)]);
      if (overviewResponse.ok) setOverview(await overviewResponse.json());
      if (sectorsResponse.ok) setSectors(await sectorsResponse.json());
      if (edgesResponse.ok) setEdges(await edgesResponse.json());
      if (stocksResponse.ok) setStocks(await stocksResponse.json());
      if (eventLinksResponse.ok) setEventLinks(await eventLinksResponse.json());
    } catch { /* Empty first-run state is an intentional product state. */ }
  };
  useEffect(() => { load(); }, []);

  const strongest = edges[0];
  const runPipeline = async (kind: "backfill" | "daily") => {
    setPipelineState(kind === "backfill" ? "Building one-year history…" : "Collecting current prices…");
    try { const response = await fetch(`${API}/api/pipelines/${kind}`, { method: "POST" }); const data = await response.json(); setPipelineState(`Temporal workflow started: ${data.workflow_id}`); } catch { setPipelineState("The API is unavailable. Start the Docker stack and try again."); }
  };
  const ask = async () => {
    if (!question.trim()) return;
    setLoading(true); setAnswer(null); setResearchMetrics(null);
    try {
      const response = await fetch(`${API}/api/research`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }) });
      const { session_id } = await response.json();
      let completed = false;
      for (let attempt = 0; attempt < 12; attempt += 1) {
        await new Promise(resolve => setTimeout(resolve, 900));
        const status = await fetch(`${API}/api/research/${session_id}`);
        if (status.ok) { const result = await status.json(); if (result.status === "completed") { setAnswer(result.answer); setResearchMetrics(result.metrics); await load(); completed = true; break; } }
      }
      if (!completed) setAnswer("Research is running in Temporal. This view will update once its tool loop completes.");
    } catch { setAnswer("Could not start the research agent. Make sure the API and Temporal worker are running."); }
    finally { setLoading(false); }
  };

  const displaySectors = sectors.length ? sectors : [
    { symbol: "XLK", close: 231.40, return_5d: 2.84, as_of: "Demo" }, { symbol: "XLE", close: 86.20, return_5d: 1.72, as_of: "Demo" },
    { symbol: "XLI", close: 142.18, return_5d: .67, as_of: "Demo" }, { symbol: "XLV", close: 147.33, return_5d: -.56, as_of: "Demo" }, { symbol: "XLF", close: 43.91, return_5d: -1.18, as_of: "Demo" }, { symbol: "XLU", close: 74.02, return_5d: -2.05, as_of: "Demo" },
  ];
  const status = overview?.as_of_date ? "LIVE DATA" : "AWAITING HISTORY";

  return <main className="min-h-screen bg-canvas text-slate-100">
    <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-line bg-canvas/90 px-5 backdrop-blur md:px-9">
      <div className="flex items-center gap-6"><div className="flex items-baseline gap-2"><span className="text-lg font-semibold tracking-tight">market<span className="text-lime">eagle</span></span><span className="hidden font-mono text-[10px] text-mist sm:block">RESEARCH SYSTEM / 01</span></div><div className="hidden h-4 w-px bg-line md:block" /><Badge className={overview?.as_of_date ? "border-lime/30 text-lime" : ""}><span className={cn("mr-1.5 inline-block h-1.5 w-1.5 rounded-full", overview?.as_of_date ? "bg-lime" : "bg-amber-300")} />{status}</Badge></div>
      <div className="flex items-center gap-2"><Button variant="ghost" size="sm" onClick={() => runPipeline("daily")}><RefreshCw className="h-3.5 w-3.5" />Sync</Button><Button size="sm" onClick={() => runPipeline("backfill")}><Database className="h-3.5 w-3.5" />Build history</Button></div>
    </header>

    <div className="grid-noise border-b border-line px-5 py-10 md:px-9 md:py-14">
      <div className="mx-auto grid max-w-[1500px] grid-cols-1 gap-10 xl:grid-cols-[1.05fr_.95fr] xl:items-end">
        <div className="animate-rise"><div className="mb-5 flex items-center gap-2 font-mono text-[11px] tracking-[.18em] text-lime"><Activity className="h-3.5 w-3.5" />MARKET MEMORY, NOT MARKET NOISE</div><h1 className="max-w-3xl text-4xl font-semibold leading-[1.04] tracking-[-.055em] md:text-6xl">Ask the market<br /><span className="text-mist">what it remembers.</span></h1><p className="mt-5 max-w-xl text-sm leading-6 text-mist">Daily prices become persistent evidence. Temporal workflows collect, analyze, and connect sector behavior—then the research agent answers from the record.</p></div>
        <div className="animate-rise border-l border-lime/60 bg-panel/60 p-5 [animation-delay:120ms] md:p-6"><div className="mb-3 flex items-center justify-between"><span className="font-mono text-[10px] uppercase tracking-[.16em] text-mist">Market pulse / 30 sessions</span><span className="font-mono text-xs text-lime">+8.4%</span></div><div className="h-36"><ResponsiveContainer width="100%" height="100%"><AreaChart data={sampleTrend}><defs><linearGradient id="pulse" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#B7F34A" stopOpacity=".25"/><stop offset="100%" stopColor="#B7F34A" stopOpacity="0"/></linearGradient></defs><Tooltip contentStyle={{ background: "#121722", border: "1px solid #252C38", fontSize: 12 }} /><Area type="monotone" dataKey="value" stroke="#B7F34A" strokeWidth={2} fill="url(#pulse)" /></AreaChart></ResponsiveContainer></div><div className="mt-3 flex justify-between border-t border-line pt-3 font-mono text-[10px] text-mist"><span>11 SECTOR INSTRUMENTS</span><span>{overview?.bar_count?.toLocaleString() ?? "—"} BARS RETAINED</span><span>US EQUITIES</span></div></div>
      </div>
    </div>

    <section className="mx-auto max-w-[1500px] px-5 py-8 md:px-9"><div className="mb-4 flex items-center justify-between"><div><h2 className="text-sm font-medium">Sector tape</h2><p className="mt-1 text-xs text-mist">Five-session return · sorted by relative momentum</p></div><span className="font-mono text-[10px] text-mist">AS OF {overview?.as_of_date ?? "NOT YET COLLECTED"}</span></div><div className="grid grid-cols-2 border-l border-t border-line sm:grid-cols-3 lg:grid-cols-6">{displaySectors.map((sector, index) => <div key={sector.symbol} className="group border-b border-r border-line bg-canvas p-4 transition-colors hover:bg-panel"><div className="flex items-center justify-between"><span className="font-mono text-xs">{sector.symbol}</span><span className={cn("text-xs", sector.return_5d >= 0 ? "text-lime" : "text-rose-300")}>{sector.return_5d >= 0 ? <ArrowUpRight className="h-3.5 w-3.5" /> : <ArrowDownRight className="h-3.5 w-3.5" />}</span></div><div className="mt-7 text-xl font-medium tracking-tight">{sector.return_5d >= 0 ? "+" : ""}{sector.return_5d.toFixed(2)}<span className="text-sm text-mist">%</span></div><div className="mt-1 font-mono text-[10px] text-mist">${sector.close.toFixed(2)} · #{index + 1}</div></div>)}</div></section>

    <section className="mx-auto max-w-[1500px] border-y border-line px-5 py-7 md:px-9"><div className="mb-4 flex items-center justify-between"><div><h2 className="text-sm font-medium">Classified stock watch</h2><p className="mt-1 text-xs text-mist">Representative equities classified against the Market Eagle sector catalog.</p></div><Badge>{stocks.length || 11} EQUITIES</Badge></div><div className="grid divide-y divide-line md:grid-cols-2 md:divide-x md:divide-y-0">{(stocks.length ? stocks.slice(0, 6) : [{symbol:"NVDA",name:"NVIDIA",sector:"Information Technology",close:181.84,return_5d:5.12},{symbol:"XOM",name:"Exxon Mobil",sector:"Energy",close:113.29,return_5d:2.31},{symbol:"JPM",name:"JPMorgan Chase",sector:"Financials",close:301.34,return_5d:-.82},{symbol:"LLY",name:"Eli Lilly",sector:"Health Care",close:837.02,return_5d:-1.20}]).map(stock => <div key={stock.symbol} className="flex items-center justify-between px-0 py-3 md:px-4"><div><span className="font-mono text-xs">{stock.symbol}</span><span className="ml-3 text-xs text-mist">{stock.name}</span><p className="mt-1 font-mono text-[10px] text-mist">{stock.sector}</p></div><div className="text-right"><div className="font-mono text-xs">${stock.close.toFixed(2)}</div><div className={cn("mt-1 font-mono text-[11px]", stock.return_5d >= 0 ? "text-lime" : "text-rose-300")}>{stock.return_5d >= 0 ? "+" : ""}{stock.return_5d.toFixed(2)}%</div></div></div>)}</div></section>

    <section className="mx-auto grid max-w-[1500px] border-t border-line xl:grid-cols-[1.08fr_.92fr]">
      <div className="border-b border-line px-5 py-8 md:border-r md:px-9"><div className="mb-6 flex items-start justify-between"><div><div className="flex items-center gap-2"><Network className="h-4 w-4 text-lime"/><h2 className="text-sm font-medium">Sector influence map</h2></div><p className="mt-1 text-xs text-mist">Lead/lag associations that cleared the configured threshold.</p></div><Badge>{overview?.relationship_count ?? 0} SIGNALS</Badge></div>
        <div className="space-y-0 border-t border-line">{(edges.length ? edges.slice(0, 5) : [{ leader: "XLE", follower: "XLI", lag_days: 2, correlation: .41, sample_size: 59, window_start: "Demo", window_end: "Demo" }, { leader: "XLK", follower: "XLC", lag_days: 1, correlation: .36, sample_size: 59, window_start: "Demo", window_end: "Demo" }]).map(edge => <div key={`${edge.leader}-${edge.follower}-${edge.lag_days}`} className="grid grid-cols-[1fr_auto_1fr_auto] items-center gap-3 border-b border-line py-4 text-sm"><span className="font-mono">{edge.leader}</span><div className="relative h-px flex-1 bg-line"><span className="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-lime" /></div><span className="font-mono">{edge.follower}</span><div className="text-right"><span className="font-mono text-xs text-lime">r {edge.correlation.toFixed(2)}</span><p className="mt-1 font-mono text-[10px] text-mist">+{edge.lag_days}D · n={edge.sample_size}</p></div></div>)}</div>
        {eventLinks.length > 0 && <div className="mt-7 border-t border-line pt-5"><div className="mb-3 flex items-center gap-2"><ExternalLink className="h-3.5 w-3.5 text-lime"/><h3 className="font-mono text-[10px] uppercase tracking-[.14em] text-mist">External event context</h3></div><div className="divide-y divide-line border-y border-line">{eventLinks.slice(0, 3).map(link => <a key={link.url} href={link.url} target="_blank" rel="noreferrer" className="group block py-3 transition-colors hover:bg-panel"><div className="flex items-start justify-between gap-4"><span className="text-xs leading-5 text-slate-200 group-hover:text-lime">{link.title}</span><ExternalLink className="mt-1 h-3 w-3 shrink-0 text-mist group-hover:text-lime"/></div><div className="mt-1 font-mono text-[10px] text-mist">{link.leader} → {link.follower} · {link.domain} · {link.seen_at.slice(0, 10)}</div></a>)}</div></div>}
        <p className="mt-4 text-[11px] leading-5 text-mist">Event links are dated external context for a relationship—not evidence of causation or trading signals.</p>
      </div>
      <div className="border-b border-line bg-panel/35 px-5 py-8 md:px-9"><div className="mb-6 flex items-center gap-2"><Sparkles className="h-4 w-4 text-lime"/><h2 className="text-sm font-medium">Daily analyst brief</h2></div>{overview?.latest_brief ? <><p className="text-xl font-medium leading-tight tracking-tight">{overview.latest_brief.headline}</p><p className="mt-4 text-sm leading-6 text-mist">{overview.latest_brief.body}</p><div className="mt-6 border-l border-lime pl-3 font-mono text-[10px] uppercase tracking-[.12em] text-mist">Evidence recorded · {overview.latest_brief.as_of_date}</div></> : <div className="border-l border-amber-300 pl-4"><p className="text-sm">No brief yet.</p><p className="mt-2 text-sm leading-6 text-mist">Build history to let the analyst generate its first evidence-backed scan.</p><Button className="mt-5" size="sm" onClick={() => runPipeline("backfill")}><Play className="h-3.5 w-3.5"/>Start pipeline</Button></div>}</div>
    </section>

    <section className="mx-auto max-w-[1500px] px-5 py-10 md:px-9"><div className="border border-line bg-panel"><div className="flex items-center gap-2 border-b border-line px-5 py-4"><Bot className="h-4 w-4 text-lime"/><div><h2 className="text-sm font-medium">Research agent</h2><p className="text-[11px] text-mist">Durable Temporal steps · model decisions, evidence, and guard outcomes retained</p></div></div><div className="p-5"><label className="font-mono text-[10px] uppercase tracking-[.14em] text-mist">Question</label><div className="mt-2 flex flex-col gap-2 sm:flex-row"><input value={question} onChange={event => setQuestion(event.target.value)} onKeyDown={event => { if (event.key === "Enter") ask(); }} className="h-11 flex-1 border border-line bg-canvas px-3 text-sm outline-none placeholder:text-mist focus:border-lime" placeholder="Ask about trends, relationships, or real-world events…"/><Button className="h-11" onClick={ask} disabled={loading}>{loading ? <RefreshCw className="h-4 w-4 animate-spin"/> : <Search className="h-4 w-4"/>}{loading ? "Researching" : "Ask agent"}</Button></div>{answer && <div className="mt-5 border-l-2 border-lime bg-canvas px-4 py-4 text-sm leading-6 text-slate-200">{answer}</div>}{researchMetrics && <div className="mt-4 grid grid-cols-2 border-l border-t border-line sm:grid-cols-3 lg:grid-cols-6"><div className="border-b border-r border-line p-3"><p className="font-mono text-[10px] text-mist">MODEL / TOOL</p><p className="mt-1 text-sm">{researchMetrics.model_calls} / {researchMetrics.tool_calls}</p></div><div className="border-b border-r border-line p-3"><p className="font-mono text-[10px] text-mist">MODEL P95</p><p className="mt-1 text-sm">{researchMetrics.model_latency.p95_ms} ms</p><p className="text-[10px] text-mist">{researchMetrics.model_latency.total_ms} ms total</p></div><div className="border-b border-r border-line p-3"><p className="font-mono text-[10px] text-mist">TOOL P95</p><p className="mt-1 text-sm">{researchMetrics.tool_latency.p95_ms} ms</p><p className="text-[10px] text-mist">{researchMetrics.tool_latency.total_ms} ms total</p></div><div className="border-b border-r border-line p-3"><p className="font-mono text-[10px] text-mist">TOKENS</p><p className="mt-1 text-sm">{researchMetrics.prompt_tokens + researchMetrics.completion_tokens}</p></div><div className="border-b border-r border-line p-3"><p className="font-mono text-[10px] text-mist">GROUNDING</p><p className={cn("mt-1 text-sm", researchMetrics.quality?.grounded ? "text-lime" : "text-amber-300")}>{researchMetrics.quality?.grounded ? "EVIDENCE OK" : "NO EVIDENCE"}</p></div><div className="border-b border-r border-line p-3"><p className="font-mono text-[10px] text-mist">SOURCES / FAILURES</p><p className="mt-1 text-sm">{researchMetrics.quality?.cited_event_source_count ?? 0} / {researchMetrics.failed_steps}</p></div></div>}</div></div>
      {pipelineState && <div className="mt-4 flex items-center gap-2 font-mono text-[11px] text-mist"><RefreshCw className="h-3 w-3 animate-spin text-lime" />{pipelineState}</div>}
    </section>
    <footer className="border-t border-line px-5 py-5 md:px-9"><div className="mx-auto flex max-w-[1500px] justify-between font-mono text-[10px] uppercase tracking-wider text-mist"><span>Market Eagle / Evidence-first research</span><span>Not investment advice</span></div></footer>
  </main>;
}

export default App;
