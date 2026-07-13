import { SettingsHeader, Section, SettingRow } from "@/components/settings/primitives";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Switch } from "@/components/ui/Switch";
import { useSettings } from "@/settings/store";
import { cn } from "@/lib/utils";
import type { Settings } from "@/settings/schema";

type AIBoolKey =
  | "tradeExplanation"
  | "tradeScoring"
  | "signalFiltering"
  | "riskSuggestions"
  | "learningMode"
  | "memory";

const MODELS: { value: Settings["ai"]["model"]; label: string }[] = [
  { value: "decision-brain-v3", label: "Decision Brain v3 (recommended)" },
  { value: "decision-brain-v2", label: "Decision Brain v2 (stable)" },
  { value: "ema-baseline", label: "EMA Baseline (no AI)" },
];

const FEATURES: { key: AIBoolKey; label: string; desc: string }[] = [
  { key: "tradeExplanation", label: "Trade explanation", desc: "Attach a plain-language rationale to every signal." },
  { key: "tradeScoring", label: "Trade scoring", desc: "Rank each setup by expected quality before entry." },
  { key: "signalFiltering", label: "Signal filtering", desc: "Suppress low-conviction signals the model distrusts." },
  { key: "riskSuggestions", label: "Risk suggestions", desc: "Propose stop, target and sizing adjustments per trade." },
  { key: "learningMode", label: "Learning mode", desc: "Adapt weighting from closed-trade outcomes over time." },
  { key: "memory", label: "AI memory", desc: "Retain context across sessions for consistent decisions." },
];

export default function AI() {
  const { settings, update } = useSettings();
  const ai = settings.ai;
  const set = (patch: Partial<Settings["ai"]>) => update("ai", patch);
  const enabled = ai.enabled;

  return (
    <>
      <SettingsHeader
        title="AI Configuration"
        description="Tune the Decision Brain that scores, filters and explains every trade. Changes save automatically."
      />

      <div className="space-y-5">
        <Section title="Engine" description="The core model and how confident it must be to act.">
          <SettingRow label="Enable AI" description="Route signals through the Decision Brain. When off, raw strategy output is used unaltered.">
            <Switch label="Enable AI" checked={enabled} onChange={(v) => set({ enabled: v })} />
          </SettingRow>

          <SettingRow
            label="Model"
            htmlFor="ai-model"
            description="Which decision engine evaluates signals."
          >
            <div className={cn("transition-opacity", !enabled && "pointer-events-none opacity-40")}>
              <Select
                id="ai-model"
                value={ai.model}
                disabled={!enabled}
                onChange={(e) => set({ model: e.target.value as Settings["ai"]["model"] })}
                options={MODELS}
                className="sm:w-64"
              />
            </div>
          </SettingRow>

          <SettingRow
            label="AI confidence threshold"
            htmlFor="ai-confidence"
            description="Trades scoring below this confidence are skipped."
          >
            <div className={cn("flex items-center gap-2 transition-opacity sm:justify-end", !enabled && "opacity-40")}>
              <div className="relative w-32">
                <Input
                  id="ai-confidence"
                  type="number"
                  min={0}
                  max={100}
                  step={1}
                  value={String(ai.confidenceThreshold)}
                  disabled={!enabled}
                  onChange={(e) => set({ confidenceThreshold: Number(e.target.value) })}
                  className="pr-8 text-right"
                />
                <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-white/40">
                  %
                </span>
              </div>
            </div>
          </SettingRow>
        </Section>

        <Section title="Capabilities" description="What the model contributes to each decision.">
          {FEATURES.map((f) => (
            <SettingRow
              key={f.key}
              label={f.label}
              description={f.desc}
            >
              <div className={cn("transition-opacity", !enabled && "opacity-40")}>
                <Switch
                  label={f.label}
                  checked={ai[f.key]}
                  disabled={!enabled}
                  onChange={(v) => set({ [f.key]: v } as Partial<Settings["ai"]>)}
                />
              </div>
            </SettingRow>
          ))}
        </Section>

        <Section
          title="Prompt customization"
          description="Extra guidance appended to the model's system context — house rules, biases to avoid, instruments to favour."
        >
          <div className={cn("py-3 transition-opacity", !enabled && "opacity-40")}>
            <textarea
              id="ai-prompt"
              rows={5}
              maxLength={1000}
              disabled={!enabled}
              placeholder="e.g. Prefer trend-continuation setups. Avoid trading the first 15 minutes after a major news release."
              value={ai.prompt}
              onChange={(e) => set({ prompt: e.target.value })}
              className="w-full rounded-xl border border-line bg-ink-700/60 px-3.5 py-2.5 text-sm text-white outline-none transition-all placeholder:text-white/35 focus:border-gold/50 focus:ring-4 focus:ring-gold/10 disabled:cursor-not-allowed"
            />
            <p className="mt-1.5 text-[13px] text-white/40">{ai.prompt.length}/1000 characters.</p>
          </div>
        </Section>
      </div>
    </>
  );
}
