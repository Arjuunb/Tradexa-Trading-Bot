import Icon from "./Icon";

export interface ToastItem {
  id: number;
  msg: string;
  tone: "success" | "error" | "info";
}

const ICON: Record<string, string> = { success: "check", error: "warning", info: "info" };

export default function Toasts({ items }: { items: ToastItem[] }) {
  if (!items.length) return null;
  return (
    <div className="toast-stack">
      {items.map((t) => (
        <div className={`toast ${t.tone}`} key={t.id} role="status">
          <Icon name={ICON[t.tone]} size={15} />
          <span>{t.msg}</span>
        </div>
      ))}
    </div>
  );
}
