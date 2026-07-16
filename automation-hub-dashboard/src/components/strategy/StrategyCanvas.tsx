import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  Background, Controls, MiniMap, Handle, Position, addEdge, applyNodeChanges, applyEdgeChanges,
  type Node, type Edge, type Connection, type NodeChange, type EdgeChange, type NodeProps,
} from "reactflow";
import "reactflow/dist/style.css";
import Icon from "../common/Icon";
import type { BlockCatalog, BlockDef, CustomRule, CustomSpec } from "../../lib/api";

/* ── graph <-> spec ─────────────────────────────────────────────────────────
   Nodes: condition (a rule block) -> group (AND/OR) -> entry (BUY/SELL).
   A group may feed another group, so the graph can express (A AND B) OR C,
   which compiles to the engine's nested condition tree. */

type GData = { kind: "condition" | "group" | "entry"; rule?: CustomRule; def?: BlockDef; op?: "AND" | "OR"; side?: string };

let _seq = 1;
const nid = (p: string) => `${p}-${_seq++}`;

function graphToTree(rootId: string, nodes: Node<GData>[], edges: Edge[]): any {
  const node = nodes.find((n) => n.id === rootId);
  if (!node) return { op: "AND", rules: [] };
  const inbound = edges.filter((e) => e.target === rootId).map((e) => e.source);
  const rules = inbound.map((sid) => {
    const src = nodes.find((n) => n.id === sid);
    if (!src) return null;
    if (src.data.kind === "group") return graphToTree(sid, nodes, edges);
    return { ...(src.data.rule || { type: "ema_cross" }) };
  }).filter(Boolean);
  return { op: node.data.op || "AND", rules };
}

export function graphToSpec(nodes: Node<GData>[], edges: Edge[], base: CustomSpec): CustomSpec {
  const entry = nodes.find((n) => n.data.kind === "entry");
  const rootGroupId = entry && edges.find((e) => e.target === entry.id)?.source;
  const rootGroup = rootGroupId && nodes.find((n) => n.id === rootGroupId && n.data.kind === "group");
  const tree = rootGroup ? graphToTree(rootGroup.id, nodes, edges) : { op: "AND", rules: [] };
  return { ...base, side: (entry?.data.side as any) || base.side, entry: tree };
}

function treeToGraph(tree: any, catalog: BlockCatalog | undefined, x: number, y: { v: number },
                     nodes: Node<GData>[], edges: Edge[], parentId: string) {
  const defs = new Map<string, BlockDef>();
  catalog?.categories.forEach((c) => c.blocks.forEach((b) => defs.set(b.type, b)));
  const gid = nid("group");
  nodes.push({ id: gid, type: "group", position: { x: x + 300, y: y.v }, data: { kind: "group", op: (tree.op || "AND") } });
  edges.push({ id: nid("e"), source: gid, target: parentId, animated: true });
  (tree.rules || []).forEach((r: any) => {
    if (r.rules && r.type === undefined) {
      treeToGraph(r, catalog, x - 60, y, nodes, edges, gid);
    } else {
      const cid = nid("cond");
      nodes.push({ id: cid, type: "condition", position: { x, y: y.v }, data: { kind: "condition", rule: r, def: defs.get(r.type) } });
      edges.push({ id: nid("e"), source: cid, target: gid });
      y.v += 92;
    }
  });
  return gid;
}

export function specToGraph(spec: CustomSpec, catalog: BlockCatalog | undefined): { nodes: Node<GData>[]; edges: Edge[] } {
  const nodes: Node<GData>[] = [];
  const edges: Edge[] = [];
  const entryId = nid("entry");
  const y = { v: 40 };
  nodes.push({ id: entryId, type: "entry", position: { x: 720, y: 120 }, data: { kind: "entry", side: spec.side } });
  treeToGraph(spec.entry || { op: "AND", rules: [] }, catalog, 60, y, nodes, edges, entryId);
  return { nodes, edges };
}

/* ── custom nodes ──────────────────────────────────────────────────────────── */
function ConditionNode({ id, data }: NodeProps<GData>) {
  const cb = (window as any).__scb as (id: string, patch: any) => void;
  const rule = data.rule || { type: "?" };
  return (
    <div className={`sc-node cond ${rule.negate ? "neg" : ""}`}>
      <div className="sc-node-title">{rule.negate ? "NOT " : ""}{data.def?.label ?? rule.type}</div>
      <div className="sc-node-params">
        {(data.def?.params ?? []).map((p) => (
          p.type === "select" ? (
            <select key={p.name} value={String((rule as any)[p.name] ?? p.default)} className="sc-in"
              onChange={(e) => cb(id, { [p.name]: e.target.value })}>
              {(p.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          ) : (
            <input key={p.name} type="number" className="sc-in" title={p.label}
              value={Number((rule as any)[p.name] ?? p.default)} onChange={(e) => cb(id, { [p.name]: Number(e.target.value) })} />
          )
        ))}
      </div>
      <button className="sc-not" title="Negate" onClick={() => cb(id, { negate: !rule.negate })}>¬</button>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
function GroupNode({ id, data }: NodeProps<GData>) {
  const cb = (window as any).__scb as (id: string, patch: any) => void;
  return (
    <div className="sc-node group">
      <Handle type="target" position={Position.Left} />
      <div className="sc-logic">
        {(["AND", "OR"] as const).map((o) => (
          <button key={o} className={`sc-op ${data.op === o ? "active" : ""}`} onClick={() => cb(id, { op: o })}>{o}</button>
        ))}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
function EntryNode({ id, data }: NodeProps<GData>) {
  const cb = (window as any).__scb as (id: string, patch: any) => void;
  return (
    <div className="sc-node entry">
      <Handle type="target" position={Position.Left} />
      <div className="sc-node-title">Entry</div>
      <div className="sc-logic">
        {(["long", "short"] as const).map((s) => (
          <button key={s} className={`sc-op ${data.side === s ? "active" : ""}`} onClick={() => cb(id, { side: s })}>{s}</button>
        ))}
      </div>
    </div>
  );
}
const NODE_TYPES = { condition: ConditionNode, group: GroupNode, entry: EntryNode };

export default function StrategyCanvas({ spec, catalog, onChange }:
  { spec: CustomSpec; catalog?: BlockCatalog; onChange: (s: CustomSpec) => void }) {
  const [nodes, setNodes] = useState<Node<GData>[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const hist = useRef<{ nodes: Node<GData>[]; edges: Edge[] }[]>([]);
  const future = useRef<{ nodes: Node<GData>[]; edges: Edge[] }[]>([]);
  const loadedRef = useRef(false);

  // build the graph from the spec once (and when the catalog first arrives)
  useEffect(() => {
    if (loadedRef.current || !catalog) return;
    const g = specToGraph(spec, catalog);
    setNodes(g.nodes); setEdges(g.edges); loadedRef.current = true;
  }, [catalog, spec]);

  const push = useCallback((n: Node<GData>[], e: Edge[]) => {
    hist.current.push({ nodes, edges }); if (hist.current.length > 50) hist.current.shift();
    future.current = []; setNodes(n); setEdges(e);
  }, [nodes, edges]);

  // recompile to spec whenever the graph changes
  useEffect(() => {
    if (!loadedRef.current) return;
    onChange(graphToSpec(nodes, edges, spec));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges]);

  // edit callback used by the custom nodes (via a window handle so node props stay serialisable)
  useEffect(() => {
    (window as any).__scb = (nodeId: string, patch: any) => {
      setNodes((ns) => ns.map((n) => {
        if (n.id !== nodeId) return n;
        if (n.data.kind === "condition") return { ...n, data: { ...n.data, rule: { ...n.data.rule, ...patch } } };
        return { ...n, data: { ...n.data, ...patch } };
      }));
    };
    return () => { delete (window as any).__scb; };
  }, []);

  const onNodesChange = useCallback((c: NodeChange[]) => setNodes((ns) => applyNodeChanges(c, ns) as Node<GData>[]), []);
  const onEdgesChange = useCallback((c: EdgeChange[]) => setEdges((es) => applyEdgeChanges(c, es)), []);
  const onConnect = useCallback((c: Connection) => setEdges((es) => addEdge({ ...c, animated: true }, es)), []);

  const defs = useMemo(() => {
    const arr: BlockDef[] = []; catalog?.categories.forEach((c) => c.blocks.forEach((b) => arr.push(b))); return arr;
  }, [catalog]);

  const addCondition = (b: BlockDef) => {
    const rule: CustomRule = { type: b.type }; b.params.forEach((p) => { (rule as any)[p.name] = p.default; });
    push([...nodes, { id: nid("cond"), type: "condition", position: { x: 60, y: 40 + nodes.length * 30 }, data: { kind: "condition", rule, def: b } }], edges);
  };
  const addGroup = () => push([...nodes, { id: nid("group"), type: "group", position: { x: 360, y: 220 }, data: { kind: "group", op: "AND" } }], edges);
  const undo = () => { const p = hist.current.pop(); if (!p) return; future.current.push({ nodes, edges }); setNodes(p.nodes); setEdges(p.edges); };
  const redo = () => { const f = future.current.pop(); if (!f) return; hist.current.push({ nodes, edges }); setNodes(f.nodes); setEdges(f.edges); };

  return (
    <div>
      <div className="toolbar" style={{ gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
        <span className="dim" style={{ fontSize: 12 }}>Add block:</span>
        <select className="rule-num" onChange={(e) => { const b = defs.find((d) => d.type === e.target.value); if (b) addCondition(b); e.target.value = ""; }} value="">
          <option value="">+ condition…</option>
          {catalog?.categories.map((c) => (
            <optgroup key={c.key} label={c.label}>{c.blocks.map((b) => <option key={b.type} value={b.type}>{b.label}</option>)}</optgroup>
          ))}
        </select>
        <button className="chip-btn" onClick={addGroup}><Icon name="plus" size={12} /> AND/OR group</button>
        <button className="chip-btn" onClick={undo} disabled={!hist.current.length}><Icon name="refresh" size={12} /> Undo</button>
        <button className="chip-btn" onClick={redo} disabled={!future.current.length}>Redo</button>
        <span className="dim" style={{ fontSize: 11, marginLeft: "auto" }}>Drag from a block's right dot to a group, and the group to Entry. Select + Delete removes.</span>
      </div>
      <div style={{ height: 520, border: "1px solid var(--card-border-soft)", borderRadius: 12, overflow: "hidden", background: "#0c0c0e" }}>
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={NODE_TYPES}
          onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect}
          fitView proOptions={{ hideAttribution: true }} deleteKeyCode={["Backspace", "Delete"]}>
          <Background color="#222" gap={18} />
          <MiniMap pannable zoomable style={{ background: "#111" }} nodeColor="#eab54f" maskColor="rgba(0,0,0,0.6)" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  );
}
