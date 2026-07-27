import { useCallback, useEffect, useState } from "react";
import Card from "../common/Card";
import Icon from "../common/Icon";
import { Badge } from "../common/ui";
import {
  apiDelete, apiGet, apiPostJson,
  type Listing, type ListingsResponse, type MarketCatalog,
} from "../../lib/api";

/**
 * Published strategies — the shared shelf.
 *
 * Every row shows the verified backtest, the risk profile and the publish
 * history, because the server has no endpoint that returns a listing without
 * them. There is deliberately no "highlights only" view: a card that could show
 * net R while omitting drawdown is the exact thing this feature exists to stop.
 */
const num = (v: unknown, dp = 2) => (typeof v === "number" ? v.toFixed(dp) : "—");

const SORTS: { key: string; label: string }[] = [
  { key: "recent", label: "Recently updated" },
  { key: "net_r", label: "Net R" },
  { key: "profit_factor", label: "Profit factor" },
  { key: "win_rate", label: "Win rate" },
  { key: "drawdown", label: "Shallowest drawdown" },
  { key: "rating", label: "Rating" },
  { key: "imports", label: "Most imported" },
];

function Stars({ n }: { n: number | null }) {
  if (n === null) return <span className="dim">unrated</span>;
  return <span className="mono" title={`${n} of 5`}>{"★".repeat(Math.round(n))}{"☆".repeat(5 - Math.round(n))}</span>;
}

export default function PublishedStrategies({ toast }: { toast: (m: string, t?: string) => void }) {
  const [sort, setSort] = useState("recent");
  const [onlyFollowing, setOnlyFollowing] = useState(false);
  const [data, setData] = useState<ListingsResponse | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [library, setLibrary] = useState<MarketCatalog | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await apiGet<ListingsResponse>(
        `/marketplace/listings?sort=${sort}&following=${onlyFollowing}`));
    } catch { /* an empty shelf is not an error worth a toast */ }
  }, [sort, onlyFollowing]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { apiGet<MarketCatalog>("/marketplace").then(setLibrary).catch(() => {}); }, []);

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try {
      const r: any = await fn();
      if (r?.detail || r?.error) toast(r.detail || r.error, "error");
      else { toast(ok, "success"); await load(); }
    } catch (e: any) {
      toast(e?.message || "That action needs the webhook secret", "error");
    } finally { setBusy(false); }
  };

  const publish = (id: string, name: string) =>
    act(() => apiPostJson("/marketplace/publish", { strategy_id: id, range: "1Y" }),
        `Published ${name} with a freshly verified backtest`);

  const rate = (l: Listing) => {
    const s = window.prompt(`Rate "${l.name}" 1-5`, "4");
    if (s === null) return;
    const comment = window.prompt("Review (optional)", "") ?? "";
    void act(() => apiPostJson(`/marketplace/listings/${l.id}/rate`,
                               { stars: Number(s), comment }), "Rating saved");
  };

  const mine = (l: Listing) => !!data?.me && l.publisher === data.me;
  const followed = (who: string) => (data?.following || []).includes(who);

  return (
    <>
      <Card title="Publish a strategy"
            subtitle="the backtest is re-run on the server — you cannot supply the numbers">
        {!library?.library?.length ? (
          <div className="dim ta-center" style={{ padding: 12 }}>
            Save a strategy to your library first, then publish it here.
          </div>
        ) : (
          <table className="data-table" style={{ fontSize: 12 }}>
            <thead><tr><th>Strategy</th><th>Symbol</th><th>Version</th><th /></tr></thead>
            <tbody>
              {library.library.map((s) => (
                <tr key={s.id}>
                  <td><b>{s.name}</b></td>
                  <td className="dim">{s.symbol || "—"} · {s.timeframe || "—"}</td>
                  <td className="dim">{s.version}</td>
                  <td style={{ textAlign: "right" }}>
                    <button className="btn btn-soft btn-sm" disabled={busy}
                            onClick={() => publish(s.id, s.name)}>
                      <Icon name="external" size={12} /> Publish
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="dim" style={{ fontSize: 11, marginTop: 8 }}>
          Publishing runs a 1-year backtest here and lists <i>that</i> result. A strategy
          with too few trades to verify is refused rather than listed with a caveat.
        </div>
      </Card>

      <Card title="Published Strategies"
            subtitle={`${data?.count ?? 0} listing(s) · every row carries its verified backtest and risk`}
            right={
              <div className="toolbar" style={{ gap: 6 }}>
                <select className="input input-sm" value={sort}
                        onChange={(e) => setSort(e.target.value)}>
                  {SORTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                </select>
                <button className={`btn btn-sm ${onlyFollowing ? "btn-primary" : "btn-soft"}`}
                        onClick={() => setOnlyFollowing((v) => !v)}>
                  Following
                </button>
              </div>
            }>
        {!data?.listings.length ? (
          <div className="dim ta-center" style={{ padding: 14 }}>
            {onlyFollowing ? "No strategies from creators you follow yet."
                           : "Nothing published yet."}
          </div>
        ) : data.listings.map((l) => {
          const m = l.verified?.metrics || {};
          const isOpen = open === l.id;
          return (
            <div key={l.id} className="builder-rule" style={{ marginTop: 8, padding: 10 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <b style={{ fontSize: 13 }}>{l.name}</b>
                <Badge text={`v${l.version}`} tone="default" />
                <span className="dim" style={{ fontSize: 11.5 }}>
                  by {l.publisher} · {l.symbol} {l.timeframe}
                </span>
                <Stars n={l.rating.average} />
                <span className="dim" style={{ fontSize: 11 }}>({l.rating.count})</span>
                <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
                  {!mine(l) && (
                    <button className="btn btn-soft btn-sm" disabled={busy}
                            onClick={() => act(() => apiPostJson("/marketplace/follow",
                              { creator: l.publisher, follow: !followed(l.publisher) }),
                              followed(l.publisher) ? `Unfollowed ${l.publisher}` : `Following ${l.publisher}`)}>
                      {followed(l.publisher) ? "Unfollow" : "Follow"}
                    </button>
                  )}
                  {!mine(l) && (
                    <button className="btn btn-soft btn-sm" disabled={busy} onClick={() => rate(l)}>
                      Rate
                    </button>
                  )}
                  <button className="btn btn-primary btn-sm" disabled={busy}
                          onClick={() => act(() => apiPostJson(`/marketplace/listings/${l.id}/import`, {}),
                                             `Imported ${l.name} into your library`)}>
                    Import
                  </button>
                  {mine(l) && (
                    <button className="btn btn-soft btn-sm" disabled={busy}
                            onClick={() => act(() => apiDelete(`/marketplace/listings/${l.id}`),
                                               "Listing removed")}>
                      Delist
                    </button>
                  )}
                </div>
              </div>

              {!!l.description && (
                <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>{l.description}</div>
              )}

              <table className="data-table" style={{ marginTop: 6, fontSize: 12 }}>
                <thead>
                  <tr><th>Trades</th><th>Win %</th><th>PF</th><th>Net R</th>
                      <th>Max DD R</th><th>Worst streak</th></tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="mono">{m.total_trades ?? "—"}</td>
                    <td className="mono">{num(m.win_rate, 1)}</td>
                    <td className="mono">{num(m.profit_factor)}</td>
                    <td className={`mono ${(m.net_r ?? 0) >= 0 ? "pos" : "neg"}`}>{num(m.net_r)}</td>
                    <td className="mono neg">{num(l.risk?.max_drawdown_r)}</td>
                    <td className="mono">{l.risk?.max_consecutive_losses ?? "—"}</td>
                  </tr>
                </tbody>
              </table>

              <div className="dim" style={{ fontSize: 11, marginTop: 6 }}>
                Verified over {l.verified?.range} on {l.verified?.symbol} {l.verified?.timeframe} ·
                risk {((l.risk?.risk_per_trade_pct ?? 0) * 100).toFixed(2)}% per trade ·
                stop {l.risk?.stop} · target {l.risk?.target} · {l.imports} import(s)
                {" · "}
                <button className="btn-link" onClick={() => setOpen(isOpen ? null : l.id)}>
                  {isOpen ? "hide" : `history (${l.publish_count}) & reviews`}
                </button>
              </div>

              {isOpen && (
                <>
                  <table className="data-table" style={{ marginTop: 8, fontSize: 11.5 }}>
                    <thead><tr><th>Published</th><th>Version</th><th>Trades</th><th>Net R</th><th>PF</th><th>Max DD R</th></tr></thead>
                    <tbody>
                      {l.history.map((h, i) => (
                        <tr key={`${h.ran_at}-${i}`}>
                          <td className="dim">{(h.ran_at || "").slice(0, 10)}</td>
                          <td className="dim">v{h.version}</td>
                          <td className="mono">{h.metrics.total_trades ?? "—"}</td>
                          <td className={`mono ${(h.metrics.net_r ?? 0) >= 0 ? "pos" : "neg"}`}>{num(h.metrics.net_r)}</td>
                          <td className="mono">{num(h.metrics.profit_factor)}</td>
                          <td className="mono neg">{num(h.metrics.max_drawdown_r)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="dim" style={{ fontSize: 11, marginTop: 4 }}>
                    Every publish is recorded. Earlier results are never removed, so a
                    strategy that got worse shows a record that got worse.
                  </div>
                  {l.reviews.length > 0 && (
                    <div style={{ marginTop: 8 }}>
                      {l.reviews.map((r) => (
                        <div key={`${r.user}-${r.at}`} style={{ fontSize: 12, marginTop: 4 }}>
                          <Stars n={r.stars} /> <b>{r.user}</b>{" "}
                          <span className="dim">{r.comment}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          );
        })}
      </Card>
    </>
  );
}
