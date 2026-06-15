import { serverTime, tickers } from "../../data/mock";

export default function TickerBar() {
  return (
    <footer className="ticker">
      <div className="ticker-items">
        {tickers.map((t) => (
          <span className="ticker-item" key={t.pair}>
            <b>{t.pair}</b>
            <span className="ticker-price">{t.price}</span>
            <span className={t.change >= 0 ? "pos" : "neg"}>
              {t.change >= 0 ? "+" : ""}
              {t.change.toFixed(2)}%
            </span>
          </span>
        ))}
      </div>
      <div className="ticker-meta">
        <span className="dim">Server Time: {serverTime}</span>
        <span className="dot online" />
      </div>
    </footer>
  );
}
