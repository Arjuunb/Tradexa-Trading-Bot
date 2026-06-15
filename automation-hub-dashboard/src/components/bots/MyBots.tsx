import { useMemo, useState } from "react";
import type { Bot } from "../../types";
import Card from "../common/Card";
import Icon from "../common/Icon";
import BotRow from "./BotRow";

interface MyBotsProps {
  bots: Bot[];
  onToggle: (id: string) => void;
  onCreate: () => void;
}

type Tab = "All" | "Running" | "Paper" | "Live";

export default function MyBots({ bots, onToggle, onCreate }: MyBotsProps) {
  const [tab, setTab] = useState<Tab>("All");

  const counts = useMemo(
    () => ({
      All: bots.length,
      Running: bots.filter((b) => b.status === "Running").length,
      Paper: bots.filter((b) => b.status === "Paper").length,
      Live: bots.filter((b) => b.status === "Live").length,
    }),
    [bots],
  );

  const visible = bots.filter((b) => (tab === "All" ? true : b.status === tab));
  const tabs: Tab[] = ["All", "Running", "Paper", "Live"];

  return (
    <Card
      title="My Bots"
      className="bots-card"
      right={
        <button className="btn btn-primary" onClick={onCreate} type="button">
          <Icon name="plus" size={15} /> Create Bot
        </button>
      }
    >
      <div className="tabs">
        {tabs.map((t) => (
          <button
            key={t}
            className={`tab ${tab === t ? "active" : ""}`}
            onClick={() => setTab(t)}
            type="button"
          >
            {t} <span className="tab-count">({counts[t]})</span>
          </button>
        ))}
      </div>

      <div className="bot-list">
        {visible.map((b) => (
          <BotRow key={b.id} bot={b} onToggle={onToggle} />
        ))}
        {visible.length === 0 && <div className="empty-mini">No bots in this view.</div>}
      </div>

      <button className="link-row" type="button">
        View All Bots <Icon name="chevron" size={14} />
      </button>
    </Card>
  );
}
