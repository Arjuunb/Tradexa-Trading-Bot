import type { ReactNode } from "react";

interface CardProps {
  title?: string;
  subtitle?: string;
  right?: ReactNode;
  className?: string;
  bodyClass?: string;
  children: ReactNode;
}

export default function Card({ title, subtitle, right, className, bodyClass, children }: CardProps) {
  return (
    <section className={`card ${className ?? ""}`}>
      {(title || right) && (
        <header className="card-head">
          <div>
            {title && <h3 className="card-title">{title}</h3>}
            {subtitle && <span className="card-subtitle">{subtitle}</span>}
          </div>
          {right && <div className="card-actions">{right}</div>}
        </header>
      )}
      <div className={`card-body ${bodyClass ?? ""}`}>{children}</div>
    </section>
  );
}

export function Dropdown({ label }: { label: string }) {
  return (
    <button className="dropdown" type="button">
      {label}
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M6 9l6 6 6-6" />
      </svg>
    </button>
  );
}
