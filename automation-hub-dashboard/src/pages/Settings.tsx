import { useState } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { Field, PageHeader, Toggle } from "../components/common/ui";

export default function SettingsPage() {
  const [emailAlerts, setEmailAlerts] = useState(true);
  const [telegram, setTelegram] = useState(false);
  const [darkTheme, setDarkTheme] = useState(true);
  const [confirmLive, setConfirmLive] = useState(true);

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="Workspace, connections and default preferences"
        actions={<button className="btn btn-primary"><Icon name="check" size={14} /> Save Settings</button>}
      />

      <div className="grid-2-eq">
        <Card title="Profile">
          <div className="form-grid-2">
            <Field label="Display name"><input defaultValue="Alex Trader" /></Field>
            <Field label="Email"><input defaultValue="alex@automationhub.io" /></Field>
            <Field label="Plan"><input defaultValue="Pro" disabled /></Field>
            <Field label="Base currency"><select><option>USD ($)</option><option>EUR (€)</option><option>GBP (£)</option></select></Field>
          </div>
        </Card>

        <Card title="Exchange Connection">
          <Field label="Exchange"><select><option>Binance</option><option>Bybit</option><option>Alpaca</option></select></Field>
          <Field label="API Key" hint="Stored encrypted — placeholder only"><input type="password" placeholder="••••••••••••••••" /></Field>
          <Field label="API Secret" hint="Never shared with third parties"><input type="password" placeholder="••••••••••••••••" /></Field>
          <button className="btn btn-soft" style={{ marginTop: 8 }}><Icon name="external" size={14} /> Test Connection</button>
        </Card>
      </div>

      <div className="grid-2-eq">
        <Card title="Notifications">
          <div className="toggle-row"><div><b>Email alerts</b><span className="dim">Daily summary + critical alerts</span></div><Toggle checked={emailAlerts} onChange={setEmailAlerts} /></div>
          <div className="toggle-row"><div><b>Telegram</b><span className="dim">Real-time trade + risk alerts</span></div><Toggle checked={telegram} onChange={setTelegram} /></div>
          <div className="toggle-row"><div><b>Dark theme</b><span className="dim">Light theme coming later</span></div><Toggle checked={darkTheme} onChange={setDarkTheme} /></div>
        </Card>

        <Card title="Bot & Paper Defaults">
          <div className="form-grid-2">
            <Field label="Default risk per trade (%)"><input defaultValue="1.0" /></Field>
            <Field label="Default timeframe"><select><option>5m</option><option>15m</option><option selected>1h</option><option>4h</option></select></Field>
            <Field label="Paper starting balance ($)"><input defaultValue="10000" /></Field>
            <Field label="Data refresh interval"><select><option>1s</option><option selected>5s</option><option>15s</option><option>30s</option></select></Field>
          </div>
          <div className="toggle-row"><div><b>Confirm before going live</b><span className="dim">Require a confirmation step for live bots</span></div><Toggle checked={confirmLive} onChange={setConfirmLive} /></div>
        </Card>
      </div>
    </>
  );
}
