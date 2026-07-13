import { SettingsHeader, Section, SettingRow } from "@/components/settings/primitives";
import { EngineSyncBanner, LocalTag } from "@/components/settings/EngineSync";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Switch } from "@/components/ui/Switch";
import { useSettings } from "@/settings/store";
import { useEngineSettings } from "@/lib/hub";
import { useToast } from "@/lib/toast";
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
  const { toast } = useToast();
  const { signedIn, engine, error, push } = useEngineSettings((ok, msg) =>
    toast(msg, ok ? "success" : "error"),
  );
  const ai = settings.ai;
  const live = signedIn && engine !== null;
  const set = (patch: Partial<Settings["ai"]>) => update("ai", patch);
  const enabled = ai.enabled;
  const threshold = live ? engine.editable.min_quality_score : ai.confidenceThreshold;

  return (
    <>
      <SettingsHeader
        title="AI Configuration"
        description="Tune the Decision Brain that scores, filters and explains every trade."
      />

      <EngineSyncBanner signedIn={signedIn} error={error} />

      <div className="space-y-5">
        <Section title="Engine" description="The core model and how confident it must be to act.">
          <SettingRow label="Enable AI" description={<>Route signals through the Decision Brain.{live && <LocalTag />}</>}>
            <Switch label="Enable AI" checked={enabled} onChange={(v) => set({ enabled: v })} />
          </SettingRow>

          <SettingRow
            label="Model"
            htmlFor="ai-model"
            description={<>Which decision engine evaluates signals — switch it under Settings → Strategies.{live && <LocalTag />}</>}
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
            description={
              live
                ? "The engine's LIVE minimum quality score — setups scoring below this are rejected. 0 disables the gate."
                : "Trades scoring below this confidence are skipped."
            }
          >
            <div className={cn("flex items-center gap-2 transition-opacity sm:justify-end", !enabled && "opacity-40")}>
              <div className="relative w-32">
                <Input
                  id="ai-confidence"
                  type="number"
                  min={0}
                  max={100}
                  step={1}
                  value={String(threshold)}
                  disabled={!enabled}
                  onChange={(e) => {
                    const n = Number(e.target.value);
                    set({ confidenceThreshold: n });
                    if (live && n >= 0 && n <= 100) push({ min_quality_score: Math.round(n) });
                  }}
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
              description={<>{f.desc}{live && <LocalTag />}</>}
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
