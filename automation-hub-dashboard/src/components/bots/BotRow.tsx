import type { Bot } from "../../types";
import Icon from "../common/Icon";
import { statusColor } from "../../theme";

interface BotRowProps {
  bot: Bot;
  onToggle: (id: string) => void;
}

export default function BotRow({ bot, onToggle }: BotRowProps) {
  const isActive = bot.status === "Live" || bot.status === "Running";
  const pnlClass = bot.todayPnl > 0 ? "pos" : bot.todayPnl < 0 ? "neg" : "dim";
  const pnlText =
    bot.todayPnl === 0
      ? "$0.00"
      : `${bot.todayPnl > 0 ? "+" : "-"}$${Math.abs(bot.todayPnl).toFixed(2)}`;

  return (
    <div className="bot-row">
      <div className="bot-avatar" style={{ background: `${statusColor(bot.status)}22`, color: statusColor(bot.status) }}>
        <Icon name="robot" size={16} />
      </div>
      <div className="bot-info">
        <div className="bot-name-row">
          <b>{bot.name}</b>
          <span className="status-tag" style={{ background: `${statusColor(bot.status)}22`, color: statusColor(bot.status) }}>
            {bot.status}
          </span>
        </div>
        <span className="bot-meta">
          {bot.pair} · {bot.timeframe}
        </span>
      </div>
      <div className="bot-pnl">
        <span className="bot-pnl-label">P&amp;L 7D</span>
        <span className={pnlClass}>{pnlText}</span>
      </div>
      <button
        className={`icon-btn play ${isActive ? "is-active" : ""}`}
        onClick={() => onToggle(bot.id)}
        aria-label={isActive ? "Pause bot" : "Start bot"}
      >
        <Icon name={isActive ? "pause" : "play"} size={16} />
      </button>
    </div>
  );
}
