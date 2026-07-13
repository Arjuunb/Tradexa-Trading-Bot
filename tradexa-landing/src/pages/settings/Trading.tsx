import { useState, type KeyboardEvent } from "react";
import { X } from "lucide-react";
import { SettingsHeader, Section, SettingRow } from "@/components/settings/primitives";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { useSettings } from "@/settings/store";
import type { Settings } from "@/settings/schema";

type TradingKey = keyof Settings["trading"];

const EXCHANGES = ["Binance", "Bybit", "OKX", "Hyperliquid", "Bitget", "Coinbase", "Kraken"];
const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"];

function Num({
  value,
  onChange,
  suffix,
  step = 1,
  min = 0,
  max,
}: {
  value: number;
  onChange: (n: number) => void;
  suffix?: string;
  step?: number;
  min?: number;
  max?: number;
}) {
  return (
    <div className="flex items-center gap-2 sm:justify-end">
      <div className="relative w-32">
        <Input
          type="number"
          value={String(value)}
          step={step}
          min={min}
          max={max}
          onChange={(e) => onChange(Number(e.target.value))}
          className="pr-8 text-right"
        />
        {suffix && (
          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-white/40">
            {suffix}
          </span>
        )}
      </div>
    </div>
  );
}

function PairsInput({
  pairs,
  onChange,
}: {
  pairs: string[];
  onChange: (next: string[]) => void;
}) {
  const [draft, setDraft] = useState<string>("");

  const add = () => {
    const value = draft.trim().toUpperCase();
    if (!value || pairs.includes(value)) {
      setDraft("");
      return;
    }
    onChange([...pairs, value]);
    setDraft("");
  };

  const remove = (pair: string) => onChange(pairs.filter((p) => p !== pair));

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add();
    } else if (e.key === "Backspace" && draft === "" && pairs.length > 0) {
      remove(pairs[pairs.length - 1]);
    }
  };

  return (
    <div className="space-y-2.5">
      {pairs.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {pairs.map((pair) => (
            <span
              key={pair}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line-strong bg-white/[0.04] py-1 pl-2.5 pr-1.5 text-[13px] font-medium text-white/85"
            >
              {pair}
              <button
                type="button"
                onClick={() => remove(pair)}
                className="flex h-4 w-4 items-center justify-center rounded text-white/40 transition hover:text-white"
                aria-label={`Remove ${pair}`}
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={add}
          placeholder="Add pair, e.g. BTCUSDT"
          className="uppercase placeholder:normal-case"
        />
      </div>
    </div>
  );
}

export default function Trading() {
  const { settings, update } = useSettings();
  const t = settings.trading;
  const set = (patch: Partial<Settings["trading"]>) => update("trading", patch);
  const num = (k: TradingKey, suffix?: string, step = 1, max?: number) => (
    <Num
      value={t[k] as number}
      onChange={(n) => set({ [k]: n } as Partial<Settings["trading"]>)}
      suffix={suffix}
      step={step}
      max={max}
    />
  );

  return (
    <>
      <SettingsHeader
        title="Trading Preferences"
        description="Defaults the engine applies to new strategies and orders. Autosaves."
      />

      <div className="space-y-5">
        <Section title="Market & venue" description="Where and what Tradexa trades by default.">
          <SettingRow label="Preferred exchange" description="Primary venue for new positions.">
            <Select
              options={EXCHANGES.map((e) => ({ value: e.toLowerCase(), label: e }))}
              value={t.preferredExchange}
              onChange={(e) => set({ preferredExchange: e.target.value })}
            />
          </SettingRow>
          <SettingRow
            label="Preferred trading pairs"
            description="Symbols the scanner watches. Add or remove as you like."
            stacked
          >
            <PairsInput pairs={t.pairs} onChange={(pairs) => set({ pairs })} />
          </SettingRow>
          <SettingRow label="Default timeframe" description="Candle interval strategies use by default.">
            <Select
              options={TIMEFRAMES.map((tf) => ({ value: tf, label: tf }))}
              value={t.defaultTimeframe}
              onChange={(e) => set({ defaultTimeframe: e.target.value })}
            />
          </SettingRow>
        </Section>

        <Section title="Sizing & risk profile" description="How positions are sized and how aggressive the engine is.">
          <SettingRow label="Risk mode" description="Overall appetite applied across strategies.">
            <SegmentedControl<Settings["trading"]["riskMode"]>
              value={t.riskMode}
              onChange={(v) => set({ riskMode: v })}
              options={[
                { value: "conservative", label: "Conservative" },
                { value: "balanced", label: "Balanced" },
                { value: "aggressive", label: "Aggressive" },
              ]}
            />
          </SettingRow>
          <SettingRow label="Position sizing" description="Method used to size each entry.">
            <Select
              options={[
                { value: "fixed", label: "Fixed" },
                { value: "percent_equity", label: "% of equity" },
                { value: "risk_based", label: "Risk based" },
                { value: "kelly", label: "Kelly" },
              ]}
              value={t.positionSizing}
              onChange={(e) =>
                set({ positionSizing: e.target.value as Settings["trading"]["positionSizing"] })
              }
            />
          </SettingRow>
          <SettingRow label="Default leverage" description="Applied when a strategy sets none. Capped by Risk limits.">
            {num("defaultLeverage", "×", 1, 125)}
          </SettingRow>
          <SettingRow label="Maximum simultaneous trades" description="Open positions allowed at once.">
            {num("maxSimultaneousTrades", undefined, 1, 50)}
          </SettingRow>
        </Section>

        <Section title="Order execution" description="How orders are routed and priced.">
          <SettingRow label="Order type" description="Default order used for entries.">
            <SegmentedControl<Settings["trading"]["orderType"]>
              value={t.orderType}
              onChange={(v) => set({ orderType: v })}
              options={[
                { value: "market", label: "Market" },
                { value: "limit", label: "Limit" },
                { value: "stop_limit", label: "Stop Limit" },
              ]}
            />
          </SettingRow>
          <SettingRow label="Slippage tolerance" description="Maximum price drift accepted on fills.">
            {num("slippageTolerance", "%", 0.05, 5)}
          </SettingRow>
          <SettingRow label="Commission" description="Assumed taker fee for backtests and sizing.">
            {num("commission", "%", 0.01, 2)}
          </SettingRow>
          <SettingRow label="Spread" description="Assumed bid/ask spread for modelling.">
            {num("spread", "%", 0.01, 2)}
          </SettingRow>
        </Section>
      </div>
    </>
  );
}
