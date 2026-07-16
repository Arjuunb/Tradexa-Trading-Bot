import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { Badge, PageHeader, StatCard } from "../components/common/ui";
import { useApp } from "../app-context";
import {
  apiGet, apiPostJson, useLive,
  type AssetClasses, type MarketPrefs, type SymbolRow, type SymbolInfo,
} from "../lib/api";

const CLASS_LABEL: Record<string, string> = {
  crypto: "Crypto", stock: "Stocks", etf: "ETFs", index: "Indices",
  forex: "Forex", commodity: "Commodities",
};
const money = (n?: number) => (n == null ? "—" : n.toLocaleString(undefined, { maximumFractionDigits: n >= 100 ? 2 : 6 }));

export default function SymbolExplorerPage() {
  const { toast } = useApp();
  const { data: classes } = useLive<AssetClasses>("/symbols/asset-classes", 60000);
  const [prefs, setPrefs] = useState<MarketPrefs | null>(null);

  // tab: an asset class, "favorites", or "wl:<id>"
  const [tab, setTab] = useState<string>("crypto");
  const [quote, setQuote] = useState<string>("");     // "", USDT, BTC
  const [type, setType] = useState<string>("");       // "", spot, futures
  const [rows, setRows] = useState<SymbolRow[]>([]);
  const [selected, setSelected] = useState<string>("BTC/USDT");

  // search
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SymbolRow[]>([]);
  const [open, setOpen] = useState(false);
  const searchRef = useRef<number | null>(null);

  const refreshPrefs = useCallback(() => {
    apiGet<MarketPrefs>("/market/prefs").then(setPrefs).catch(() => {});
  }, []);
  useEffect(() => { refreshPrefs(); }, [refreshPrefs]);

  // load the list for the active tab / filters
  const loadList = useCallback(() => {
    let path: string;
    if (tab === "favorites") {
      path = "/symbols?favorites=true";
    } else if (tab.startsWith("wl:")) {
      path = ""; // handled from prefs below
    } else {
      const p = new URLSearchParams({ asset_class: tab });
      if (tab === "crypto" && quote) p.set("quote", quote);
      if (tab === "crypto" && type) p.set("type", type);
      p.set("limit", "400");
      path = `/symbols?${p.toString()}`;
    }
    if (!path) return;
    apiGet<{ symbols: SymbolRow[] }>(path).then((r) => setRows(r.symbols ?? [])).catch(() => setRows([]));
  }, [tab, quote, type]);
  useEffect(() => { loadList(); }, [loadList]);

  // watchlist tab: resolve its symbols to rows via search-by-ticker is overkill;
  // fetch the full universe once and filter. Simpler: use the favorites endpoint
  // shape by asking /symbols for each — instead we read the whole class list.
  const activeWatchlist = useMemo(
    () => (tab.startsWith("wl:") ? prefs?.watchlists.find((w) => "wl:" + w.id === tab) : undefined),
    [tab, prefs]);
  useEffect(() => {
    if (!activeWatchlist) return;
    // pull the full universe (all classes) and filter to the watchlist tickers
    apiGet<{ symbols: SymbolRow[] }>("/symbols?limit=2000").then((r) => {
      const want = new Set(activeWatchlist.symbols.map((s) => s.toUpperCase()));
      setRows((r.symbols ?? []).filter((s) => want.has(s.ticker.toUpperCase()) || want.has(s.symbol.toUpperCase())));
    }).catch(() => setRows([]));
  }, [activeWatchlist]);

  // debounced autocomplete
  useEffect(() => {
    if (searchRef.current) window.clearTimeout(searchRef.current);
    if (!q.trim()) { setResults([]); return; }
    searchRef.current = window.setTimeout(() => {
      apiGet<{ results: SymbolRow[] }>(`/symbols/search?q=${encodeURIComponent(q)}&limit=12`)
        .then((r) => { setResults(r.results ?? []); setOpen(true); }).catch(() => setResults([]));
    }, 180);
    return () => { if (searchRef.current) window.clearTimeout(searchRef.current); };
  }, [q]);

  // selected symbol market info
  const info = useLive<SymbolInfo>(`/symbols/info?symbol=${encodeURIComponent(selected)}`, 15000);

  const favSet = useMemo(() => new Set((prefs?.favorites ?? []).map((f) => f.toUpperCase())), [prefs]);
  const pinSet = useMemo(() => new Set((prefs?.pinned ?? []).map((p) => p.toUpperCase())), [prefs]);
  const isFav = (s: SymbolRow) => favSet.has(s.ticker.toUpperCase()) || favSet.has(s.symbol.toUpperCase());
  const isPin = (s: SymbolRow) => pinSet.has(s.ticker.toUpperCase()) || pinSet.has(s.symbol.toUpperCase());

  const toggleFav = async (s: SymbolRow) => {
    try { await apiPostJson("/market/favorite", { symbol: s.ticker, on: !isFav(s) }); refreshPrefs(); }
    catch { toast("Could not update favorite", "error"); }
  };
  const togglePin = async (s: SymbolRow) => {
    try { await apiPostJson("/market/pin", { symbol: s.ticker, on: !isPin(s) }); refreshPrefs(); }
    catch { toast("Could not pin", "error"); }
  };
  const newWatchlist = async () => {
    const name = window.prompt("New watchlist name (e.g. Crypto, US Stocks, Forex, Scalping):");
    if (!name?.trim()) return;
    try { await apiPostJson("/market/watchlist", { name }); refreshPrefs(); toast(`Created “${name}”`, "success"); }
    catch { toast("Could not create watchlist", "error"); }
  };
  const addToWatchlist = async (wid: string, s: SymbolRow, on: boolean) => {
    try { await apiPostJson("/market/watchlist/symbol", { id: wid, symbol: s.ticker, on }); refreshPrefs(); }
    catch { toast("Could not update watchlist", "error"); }
  };
  const deleteWatchlist = async (wid: string) => {
    if (!window.confirm("Delete this watchlist?")) return;
    try { await apiPostJson("/market/watchlist/delete", { id: wid }); refreshPrefs(); setTab("crypto"); }
    catch { toast("Could not delete watchlist", "error"); }
  };

  // sort: pinned first, then favorites, then name
  const sorted = useMemo(() => [...rows].sort((a, b) => {
    const pa = isPin(a) ? 0 : isFav(a) ? 1 : 2, pb = isPin(b) ? 0 : isFav(b) ? 1 : 2;
    return pa - pb || a.symbol.localeCompare(b.symbol);
  }), [rows, favSet, pinSet]);

  const pick = (sym: string) => { setSelected(sym); setOpen(false); setQ(""); };
  const up = (info.data?.change_24h_pct ?? 0) >= 0;

  return (
    <>
      <PageHeader title="Symbol Explorer"
        subtitle="Multi-asset universe — crypto auto-synced from the exchange (CCXT); stocks, ETFs, indices, forex & commodities from the reference catalog" />

      <div className="stat-row">
        <StatCard label="Total Symbols" value={String(classes?.total ?? "—")} />
        <StatCard label="Crypto Feed" value={classes?.crypto_source?.startsWith("live") ? "Live (CCXT)" : "Seed list"}
          tone={classes?.crypto_source?.startsWith("live") ? "green" : "amber"} />
        <StatCard label="Favorites" value={String(prefs?.favorites?.length ?? 0)} tone="gold" />
        <StatCard label="Watchlists" value={String(prefs?.watchlists?.length ?? 0)} />
      </div>

      {/* search */}
      <Card title="">
        <div className="sym-search">
          <Icon name="search" size={16} className="dim" />
          <input className="sym-search-input" placeholder="Search ticker or name — BTC, Apple, EUR/USD, Gold…"
            value={q} onChange={(e) => setQ(e.target.value)} onFocus={() => q && setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 150)} />
          {open && results.length > 0 && (
            <div className="sym-dropdown">
              {results.map((r) => (
                <button key={r.symbol + r.asset_class} className="sym-opt" onMouseDown={() => pick(r.symbol)}>
                  <span className="sym-opt-tk"><b>{r.symbol}</b> <span className="dim">{r.name}</span></span>
                  <Badge text={CLASS_LABEL[r.asset_class] ?? r.asset_class} tone="default" />
                </button>
              ))}
            </div>
          )}
        </div>
      </Card>

      {/* tabs */}
      <div className="toolbar" style={{ flexWrap: "wrap", gap: 6 }}>
        <div className="chips" style={{ flexWrap: "wrap" }}>
          {(classes?.asset_classes ?? []).map((c) => (
            <button key={c.asset_class} className={`chip-btn ${tab === c.asset_class ? "active" : ""}`}
              onClick={() => setTab(c.asset_class)}>{CLASS_LABEL[c.asset_class] ?? c.asset_class} <span className="dim">{c.count}</span></button>
          ))}
          <button className={`chip-btn ${tab === "favorites" ? "active" : ""}`} onClick={() => setTab("favorites")}>
            <Icon name="star" size={12} /> Favorites</button>
          {(prefs?.watchlists ?? []).map((w) => (
            <button key={w.id} className={`chip-btn ${tab === "wl:" + w.id ? "active" : ""}`} onClick={() => setTab("wl:" + w.id)}>
              {w.name} <span className="dim">{w.symbols.length}</span></button>
          ))}
          <button className="chip-btn" onClick={newWatchlist}><Icon name="plus" size={12} /> Watchlist</button>
        </div>
        {tab === "crypto" && (
          <div className="chips">
            {["", "USDT", "BTC"].map((qq) => (
              <button key={qq || "all"} className={`chip-btn ${quote === qq ? "active" : ""}`} onClick={() => setQuote(qq)}>{qq || "All quotes"}</button>
            ))}
            {["", "spot", "futures"].map((tt) => (
              <button key={tt || "any"} className={`chip-btn ${type === tt ? "active" : ""}`} onClick={() => setType(tt)}>{tt ? tt[0].toUpperCase() + tt.slice(1) : "Any type"}</button>
            ))}
          </div>
        )}
        {activeWatchlist && (
          <button className="btn btn-soft" onClick={() => deleteWatchlist(activeWatchlist.id)}>
            <Icon name="close" size={13} /> Delete “{activeWatchlist.name}”</button>
        )}
      </div>

      <div className="grid-2-1">
        {/* symbol table */}
        <Card title={tab.startsWith("wl:") ? activeWatchlist?.name ?? "Watchlist"
          : tab === "favorites" ? "Favorites" : CLASS_LABEL[tab] ?? "Symbols"}
          subtitle={`${sorted.length} symbols`}>
          <div style={{ maxHeight: 460, overflowY: "auto" }}>
            <table className="data-table" style={{ fontSize: 12.5 }}>
              <thead><tr><th></th><th>Symbol</th><th>Name</th><th>Type</th><th>Exchange</th><th>Status</th><th></th></tr></thead>
              <tbody>
                {sorted.map((s) => (
                  <tr key={s.symbol + s.asset_class} className={selected === s.symbol ? "active-row" : ""}
                    style={{ cursor: "pointer" }} onClick={() => setSelected(s.symbol)}>
                    <td onClick={(e) => { e.stopPropagation(); toggleFav(s); }} title="Favorite"
                      style={{ color: isFav(s) ? "var(--gold)" : "var(--dim)", width: 24 }}>
                      <Icon name="star" size={14} /></td>
                    <td><b>{s.symbol}</b></td>
                    <td className="dim">{s.name}</td>
                    <td><Badge text={s.type} tone={s.type === "futures" ? "amber" : "default"} /></td>
                    <td className="dim">{s.exchange}</td>
                    <td><Badge text={s.session === "24/7" ? "24/7" : s.session} tone="default" /></td>
                    <td onClick={(e) => { e.stopPropagation(); togglePin(s); }} title="Pin"
                      style={{ color: isPin(s) ? "var(--sky, #7cb9e8)" : "var(--dim)", width: 24 }}>
                      <Icon name="pin" size={13} /></td>
                  </tr>
                ))}
                {sorted.length === 0 && <tr><td colSpan={7} className="dim ta-center" style={{ padding: 16 }}>No symbols.</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>

        {/* market info panel */}
        <Card title="Market Info" subtitle={selected}>
          {!info.data?.found ? <div className="dim" style={{ padding: 12 }}>Select a symbol.</div> : (
            <div className="sym-info">
              <div className="sym-info-head">
                <div><h2 style={{ margin: 0 }}>{info.data.symbol}</h2><span className="dim">{info.data.name}</span></div>
                <Badge text={info.data.market_status === "open" ? "Market Open" : "Market Closed"}
                  tone={info.data.market_status === "open" ? "green" : "red"} />
              </div>
              {info.data.price_available ? (
                <div className="stat-row" style={{ marginTop: 10 }}>
                  <StatCard label="Price" value={money(info.data.price)} />
                  <StatCard label="24H Change" value={`${up ? "+" : ""}${info.data.change_24h_pct ?? 0}%`} tone={up ? "green" : "red"} />
                  <StatCard label="24H Volume" value={money(info.data.volume_24h)} />
                </div>
              ) : (
                <div className="banner" style={{ marginTop: 10 }}>
                  <Icon name="info" size={14} /> {info.data.note ?? "Live quote not available for this asset class yet."}
                </div>
              )}
              <div className="detail-grid" style={{ marginTop: 12 }}>
                <div><span className="dim">Asset type</span><b>{CLASS_LABEL[info.data.asset_class] ?? info.data.asset_class}</b></div>
                <div><span className="dim">Exchange</span><b>{info.data.exchange}</b></div>
                <div><span className="dim">Order type</span><b>{info.data.type}</b></div>
                <div><span className="dim">Trading session</span><b>{info.data.session}</b></div>
                {info.data.base && <div><span className="dim">Base / Quote</span><b>{info.data.base} / {info.data.quote}</b></div>}
                {info.data.source && <div><span className="dim">Data source</span><b>{info.data.source}</b></div>}
              </div>
              <div className="row-actions" style={{ marginTop: 12 }}>
                <button className="btn btn-soft" onClick={() => { const s = { ticker: info.data!.ticker, symbol: info.data!.symbol } as SymbolRow; toggleFav(s); }}>
                  <Icon name="star" size={13} /> {favSet.has(info.data.ticker.toUpperCase()) ? "Unfavorite" : "Add favorite"}</button>
                {(prefs?.watchlists ?? []).map((w) => {
                  const inWl = w.symbols.map((x) => x.toUpperCase()).includes(info.data!.ticker.toUpperCase());
                  return (
                    <button key={w.id} className={`chip-btn ${inWl ? "active" : ""}`}
                      onClick={() => addToWatchlist(w.id, { ticker: info.data!.ticker } as SymbolRow, !inWl)}>
                      {inWl ? "✓ " : "+ "}{w.name}</button>
                  );
                })}
              </div>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
