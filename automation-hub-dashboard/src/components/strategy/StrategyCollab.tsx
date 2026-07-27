import { useCallback, useEffect, useState } from "react";
import Card from "../common/Card";
import Icon from "../common/Icon";
import { Badge } from "../common/ui";
import {
  apiDelete, apiGet, apiPatchJson, apiPostJson,
  type Changelog, type StrategyComment, type StrategyShares,
} from "../../lib/api";

/**
 * Versioning & collaboration for one strategy.
 *
 * The change log is not authored — the server derives each line by diffing two
 * stored version snapshots, so what you read here is the spec itself rather
 * than somebody's summary of it. That is what keeps an old version reproducible:
 * the log cannot drift away from the artefact it describes.
 *
 * Comments are the opposite: they ARE opinions, so they carry an author and an
 * edited stamp, and only their author can change them.
 */
export default function StrategyCollab({ sid, toast }: {
  sid: string; toast: (m: string, t?: string) => void;
}) {
  const [log, setLog] = useState<Changelog | null>(null);
  const [comments, setComments] = useState<StrategyComment[]>([]);
  const [shares, setShares] = useState<StrategyShares | null>(null);
  const [draft, setDraft] = useState("");
  const [anchor, setAnchor] = useState<string>("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!sid) return;
    try {
      const [l, c, s] = await Promise.all([
        apiGet<Changelog>(`/strategy/custom/${sid}/changelog`),
        apiGet<{ comments: StrategyComment[] }>(`/strategy/custom/${sid}/comments`),
        apiGet<StrategyShares>(`/strategy/custom/${sid}/shares`),
      ]);
      setLog(l); setComments(c.comments); setShares(s);
    } catch { /* an unsaved strategy simply has no collaboration yet */ }
  }, [sid]);

  useEffect(() => { void load(); }, [load]);

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try {
      const r: any = await fn();
      if (r?.detail || r?.error) toast(r.detail || r.error, "error");
      else { toast(ok, "success"); await load(); }
    } catch (e: any) { toast(e?.message || "That action needs the webhook secret", "error"); }
    finally { setBusy(false); }
  };

  const post = () => {
    if (!draft.trim()) return;
    void act(() => apiPostJson(`/strategy/custom/${sid}/comments`,
      { body: draft, version: anchor || undefined }), "Comment posted")
      .then(() => setDraft(""));
  };

  const editComment = (c: StrategyComment) => {
    const next = window.prompt("Edit your comment", c.body);
    if (next === null) return;
    void act(() => apiPatchJson(`/strategy/custom/${sid}/comments/${c.id}`, { body: next }),
             "Comment updated");
  };

  const addShare = () => {
    const user = window.prompt("Share with (username)");
    if (!user) return;
    const role = window.prompt(`Role — ${(shares?.roles || []).join(" / ")}`, "viewer");
    if (!role) return;
    void act(() => apiPostJson(`/strategy/custom/${sid}/share`, { user, role }),
             `Shared with ${user}`);
  };

  if (!sid) return null;

  return (
    <>
      <Card title="Change Log"
            subtitle="derived by diffing saved versions — nobody writes these notes"
            right={log ? <Badge text={`${log.versions ?? 0} version(s)`} tone="default" /> : null}>
        {!log?.entries?.length ? (
          <div className="dim" style={{ fontSize: 12.5, padding: 8 }}>
            {log?.note || "Save an edit to start the history."}
          </div>
        ) : (
          <div>
            {[...log.entries].reverse().map((e) => (
              <div key={String(e.v)} className="builder-rule"
                   style={{ marginTop: 8, padding: 10 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <Badge text={e.v === "current" ? "current" : `v${e.v}`}
                         tone={e.v === "current" ? "green" : "default"} />
                  <span className="dim" style={{ fontSize: 11.5 }}>
                    {(e.at || "").slice(0, 16).replace("T", " ")}
                  </span>
                  {e.name && <span className="dim" style={{ fontSize: 11.5 }}>· {e.name}</span>}
                </div>
                <ul style={{ margin: "6px 0 0 16px", fontSize: 12 }}>
                  {e.changes.map((c, i) => <li key={i}>{c}</li>)}
                </ul>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="Discussion"
            subtitle="comments belong to their authors — an edit is always stamped">
        <div className="toolbar" style={{ gap: 6, alignItems: "flex-start" }}>
          <input className="input" style={{ flex: 1 }} value={draft}
                 placeholder="Ask a question or leave a note for the team…"
                 onChange={(e) => setDraft(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Enter") post(); }} />
          <select className="input input-sm" value={anchor}
                  onChange={(e) => setAnchor(e.target.value)}>
            <option value="">no version</option>
            {(log?.entries || []).map((e) => (
              <option key={String(e.v)} value={String(e.v)}>
                {e.v === "current" ? "current" : `v${e.v}`}
              </option>
            ))}
          </select>
          <button className="btn btn-primary btn-sm" disabled={busy || !draft.trim()}
                  onClick={post}>
            <Icon name="check" size={12} /> Post
          </button>
        </div>

        {!comments.length ? (
          <div className="dim" style={{ fontSize: 12.5, padding: 8 }}>No comments yet.</div>
        ) : comments.map((c) => (
          <div key={c.id} style={{ marginTop: 8, fontSize: 12.5,
                                   marginLeft: c.reply_to ? 18 : 0 }}>
            <b>{c.author}</b>
            {c.version != null && <> <Badge text={`v${c.version}`} tone="default" /></>}
            <span className="dim" style={{ fontSize: 11 }}>
              {" "}{(c.at || "").slice(0, 16).replace("T", " ")}
              {c.edited_at && " · edited"}
            </span>
            <div style={{ marginTop: 2 }}>{c.body}</div>
            {!c.deleted && shares?.me === c.author && (
              <div className="toolbar" style={{ gap: 6, marginTop: 2 }}>
                <button className="btn-link" onClick={() => editComment(c)}>edit</button>
                <button className="btn-link"
                        onClick={() => act(() => apiDelete(`/strategy/custom/${sid}/comments/${c.id}`),
                                           "Comment deleted")}>delete</button>
              </div>
            )}
          </div>
        ))}
      </Card>

      <Card title="Sharing"
            subtitle="viewer reads · commenter discusses · editor changes — ownership is never shared"
            right={
              <button className="btn btn-soft btn-sm" disabled={busy} onClick={addShare}>
                <Icon name="plus" size={12} /> Share
              </button>
            }>
        <div className="dim" style={{ fontSize: 11.5, marginBottom: 6 }}>
          Owner: <b>{shares?.owner || shares?.me || "you"}</b>
          {shares?.my_role && <> · your role: <b>{shares.my_role}</b></>}
        </div>
        {!Object.keys(shares?.grants || {}).length ? (
          <div className="dim" style={{ fontSize: 12.5, padding: 8 }}>
            Not shared with anyone.
          </div>
        ) : (
          <table className="data-table" style={{ fontSize: 12 }}>
            <thead><tr><th>User</th><th>Role</th><th>Granted</th><th /></tr></thead>
            <tbody>
              {Object.entries(shares!.grants).map(([user, g]) => (
                <tr key={user}>
                  <td><b>{user}</b></td>
                  <td className="dim">{g.role}</td>
                  <td className="dim">{(g.at || "").slice(0, 10)}</td>
                  <td style={{ textAlign: "right" }}>
                    <button className="btn btn-soft btn-sm" disabled={busy}
                            onClick={() => act(() => apiPostJson(`/strategy/custom/${sid}/share`,
                              { user, revoke: true }), `Revoked ${user}`)}>
                      Revoke
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
