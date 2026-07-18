/** Live grid trading engine (browser-side, paper).
 *
 *  Runs on the terminal's live candle stream — the only real-time feed available
 *  when the server's exchange access is blocked. A grid is split into gaps
 *  between adjacent levels; each gap buys at its bottom and sells at its top,
 *  booking profit net of fees. At start the grid SEEDS inventory for every level
 *  above the current price (a real grid commits capital upfront), so those gaps
 *  begin holding at the start price; levels below wait to buy. Deterministic and
 *  pure so it's easy to test and persist (localStorage). Fills are simulated on
 *  CLOSED candles using their [low, high] range — at most one round-trip per gap
 *  per candle, like a grid backtest. No fabricated results. */

export interface GridGap {
  lo: number; hi: number; state: "waiting_buy" | "holding";
  qty: number; buyPrice: number; buyFee: number;
}
export interface GridFill { t: string; side: "BUY" | "SELL"; price: number; qty: number; pnl: number; }
export interface GridRun {
  symbol: string; lower: number; upper: number; levels: number; geometric: boolean;
  investment: number; leverage: number; feePct: number;
  gaps: GridGap[]; orderValue: number;
  realized: number; feesPaid: number; completed: number; buys: number; sells: number;
  startedAt: string; startPrice: number; processedTs: string; fills: GridFill[];
}
export interface GridInput {
  symbol: string; lower: number; upper: number; levels: number; geometric: boolean;
  investment: number; leverage: number; feePct: number;
}

function levelPrices(lower: number, upper: number, n: number, geo: boolean): number[] {
  const out: number[] = [];
  if (n < 2 || lower <= 0 || upper <= lower) return out;
  if (geo) { const r = Math.pow(upper / lower, 1 / (n - 1)); for (let i = 0; i < n; i++) out.push(lower * Math.pow(r, i)); }
  else { const step = (upper - lower) / (n - 1); for (let i = 0; i < n; i++) out.push(lower + i * step); }
  return out;
}

export function createGridRun(c: GridInput, startTs: string, startPrice: number): GridRun | null {
  const prices = levelPrices(c.lower, c.upper, c.levels, c.geometric);
  if (prices.length < 2 || !(startPrice > 0)) return null;
  const orderValue = (c.investment / (prices.length - 1)) * c.leverage;
  const feeRate = c.feePct / 100;
  const gaps: GridGap[] = [];
  let feesPaid = 0, buys = 0;
  for (let i = 0; i < prices.length - 1; i++) {
    const lo = +prices[i].toFixed(6), hi = +prices[i + 1].toFixed(6);
    if (lo >= startPrice) {                       // above price → seed inventory at start
      const qty = orderValue / startPrice, buyFee = orderValue * feeRate;
      feesPaid += buyFee; buys += 1;
      gaps.push({ lo, hi, state: "holding", qty, buyPrice: startPrice, buyFee });
    } else {                                       // at/below price → wait to buy at lo
      gaps.push({ lo, hi, state: "waiting_buy", qty: 0, buyPrice: 0, buyFee: 0 });
    }
  }
  return {
    symbol: c.symbol, lower: c.lower, upper: c.upper, levels: c.levels, geometric: c.geometric,
    investment: c.investment, leverage: c.leverage, feePct: c.feePct,
    gaps, orderValue, realized: 0, feesPaid, completed: 0, buys, sells: 0,
    startedAt: startTs, startPrice, processedTs: startTs, fills: [],
  };
}

/** Advance the grid over one CLOSED candle. Immutable — returns a new state. */
export function gridOnCandle(s: GridRun, t: string, low: number, high: number): GridRun {
  const gaps = s.gaps.map((g) => ({ ...g }));
  let realized = s.realized, feesPaid = s.feesPaid, completed = s.completed, buys = s.buys, sells = s.sells;
  let fills = s.fills;
  const feeRate = s.feePct / 100;
  for (const g of gaps) {
    if (g.state === "waiting_buy" && low <= g.lo) {              // price dropped to the buy level
      const qty = s.orderValue / g.lo, buyFee = s.orderValue * feeRate;
      g.qty = qty; g.buyPrice = g.lo; g.buyFee = buyFee; g.state = "holding";
      feesPaid += buyFee; buys += 1;
      fills = [{ t, side: "BUY", price: g.lo, qty, pnl: -buyFee }, ...fills];
    }
    if (g.state === "holding" && high >= g.hi) {                 // price rose to the sell level
      const sellFee = g.qty * g.hi * feeRate;
      const pnl = g.qty * (g.hi - g.buyPrice) - g.buyFee - sellFee;
      realized += pnl; feesPaid += sellFee; completed += 1; sells += 1;
      fills = [{ t, side: "SELL", price: g.hi, qty: g.qty, pnl }, ...fills];
      g.qty = 0; g.buyPrice = 0; g.buyFee = 0; g.state = "waiting_buy";
    }
  }
  return { ...s, gaps, realized, feesPaid, completed, buys, sells, processedTs: t, fills: fills.slice(0, 100) };
}

export function gridUnrealized(s: GridRun, price: number): number {
  return s.gaps.reduce((a, g) => (g.state === "holding" ? a + g.qty * (price - g.buyPrice) : a), 0);
}
export function gridInventory(s: GridRun): { lots: number; cost: number } {
  let lots = 0, cost = 0;
  for (const g of s.gaps) if (g.state === "holding") { lots += 1; cost += g.qty * g.buyPrice; }
  return { lots, cost };
}
/** Buy levels of gaps currently holding inventory (drawn solid on the chart). */
export function gridHoldingLevels(s: GridRun): number[] {
  return s.gaps.filter((g) => g.state === "holding").map((g) => g.lo);
}
