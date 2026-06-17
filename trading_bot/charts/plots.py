"""Interactive Plotly chart builders (hover, zoom, responsive, dark theme).

Plotly is imported lazily so the rest of the module (api client, transforms,
safety logic, tests) works without it installed.
"""
from __future__ import annotations

from trading_bot.charts import transforms as tf

_DARK = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
             font=dict(color="#d6dde6"), margin=dict(l=44, r=16, t=24, b=30),
             xaxis=dict(gridcolor="#161d30"), yaxis=dict(gridcolor="#161d30"))


def _go():
    import plotly.graph_objects as go  # lazy
    return go


def equity_curve(curve):
    go = _go()
    ys = tf.equity_values(curve)
    fig = go.Figure(go.Scatter(y=ys, mode="lines", line=dict(color="#8b5cf6", width=2.5),
                               fill="tozeroy", fillcolor="rgba(139,92,246,0.14)", name="Equity"))
    fig.update_layout(**_DARK, hovermode="x unified")
    return fig


def drawdown_chart(curve):
    go = _go()
    dd = tf.drawdown_series(tf.equity_values(curve))
    fig = go.Figure(go.Scatter(y=dd, mode="lines", line=dict(color="#ef5350", width=1.6),
                               fill="tozeroy", fillcolor="rgba(239,83,80,0.16)", name="Drawdown"))
    fig.update_layout(**_DARK, hovermode="x unified")
    return fig


def win_loss_doughnut(wins, losses, breakeven=0):
    go = _go()
    fig = go.Figure(go.Pie(labels=["Wins", "Losses", "Breakeven"], values=[wins, losses, breakeven],
                           hole=0.62, marker=dict(colors=["#22c55e", "#ef4444", "#5b6478"])))
    fig.update_layout(**_DARK, showlegend=True)
    return fig


def bar(labels, values, color="#8b5cf6", name=""):
    go = _go()
    colors = [("#22c55e" if v >= 0 else "#ef4444") for v in values] if name == "pnl" else color
    fig = go.Figure(go.Bar(x=labels, y=values, marker_color=colors, name=name))
    fig.update_layout(**_DARK)
    return fig


def allocation_pie(labels, values):
    go = _go()
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.5))
    fig.update_layout(**_DARK, showlegend=True)
    return fig


def gauge(value, title, maximum=100, threshold=80):
    go = _go()
    fig = go.Figure(go.Indicator(mode="gauge+number", value=value, title={"text": title},
                                 gauge={"axis": {"range": [0, maximum]},
                                        "bar": {"color": "#8b5cf6"},
                                        "threshold": {"line": {"color": "#ef4444", "width": 3},
                                                      "value": threshold}}))
    fig.update_layout(**_DARK, height=220)
    return fig
