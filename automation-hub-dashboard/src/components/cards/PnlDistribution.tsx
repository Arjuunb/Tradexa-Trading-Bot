import Card from "../common/Card";
import PnlDoughnut from "../chart/PnlDoughnut";
import { pnlDistribution } from "../../data/mock";

export default function PnlDistribution() {
  return (
    <Card title="PnL Distribution" className="pnl-dist-card">
      <div className="pnl-dist">
        <PnlDoughnut />
        <div className="pnl-legend">
          {pnlDistribution.groups.map((g) => (
            <div className="pnl-legend-item" key={g.name}>
              <span className="legend-dot" style={{ background: g.color }} />
              <span className="legend-name">
                {g.name} <span className="dim">({g.count})</span>
              </span>
              <b className={g.value.startsWith("+") ? "pos" : g.value.startsWith("-") ? "neg" : "dim"}>
                {g.value}
              </b>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}
