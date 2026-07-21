import { Component, type ErrorInfo, type ReactNode } from "react";
import Icon from "./Icon";

interface Props {
  /** Changes to this key reset the boundary — pass the active route so navigating
   *  away from a crashed page recovers automatically. */
  resetKey?: string;
  children: ReactNode;
}
interface State {
  error: Error | null;
}

/** Route-level error boundary: a render crash in one page shows a recoverable
 *  fallback instead of white-screening the whole app. Resets when the route
 *  changes (resetKey) so the rest of the dashboard keeps working. */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // surface it in the console for debugging; no telemetry sink yet (see SAD §12)
    console.error("Page crashed:", error, info.componentStack);
  }

  componentDidUpdate(prev: Props) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="card" style={{ maxWidth: 520, margin: "48px auto", textAlign: "center", padding: 28 }}>
          <Icon name="warning" size={28} className="neg" />
          <h2 style={{ margin: "12px 0 6px", fontSize: 18 }}>This page hit an error</h2>
          <p className="dim" style={{ fontSize: 13, margin: "0 0 6px" }}>
            The rest of the dashboard is still working — switch pages, or reload to try again.
          </p>
          <p className="dim mono" style={{ fontSize: 11.5, margin: "0 0 16px", wordBreak: "break-word" }}>
            {this.state.error.message}
          </p>
          <button className="btn btn-primary btn-sm" onClick={() => window.location.reload()}>
            <Icon name="refresh" size={13} /> Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
