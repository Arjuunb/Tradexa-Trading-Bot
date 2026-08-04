"""Professional HTML and PDF backtest reports, with no dependencies.

**The PDF is written by hand, and that is a deliberate trade.** ReportLab,
WeasyPrint and wkhtmltopdf all work; none of them is installed, and each adds
either a compiled dependency or a headless browser to a Docker image that
currently builds from `python:3.11-slim` in under a minute. A ~150-line PDF
writer producing a text-and-rules document is a smaller, more auditable cost
than a system library added so a report can have rounded corners.

What that buys, and what it does not: the PDF is a real PDF — valid 1.4,
opens in any reader, selectable text, multi-page — and it is typographic, not
graphical. Charts live in the HTML report, which has SVG and a browser. A PDF
with fabricated chart-shaped rectangles would be worse than one without.

**Every report states its assumptions.** Slippage, commission, spread, latency,
participation and whether the ticks were synthesised all appear on the page.
A backtest result without its execution assumptions is a number without units.
"""
from __future__ import annotations

import html
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence


@dataclass
class ReportSection:
    """One block of the report. Rows are (label, value) pairs, already formatted."""

    title: str
    rows: list[tuple[str, str]] = field(default_factory=list)
    note: str = ""


@dataclass
class BacktestReport:
    """Everything a report renders. Assembled by the caller, formatted here."""

    title: str
    subtitle: str = ""
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    sections: list[ReportSection] = field(default_factory=list)
    equity_curve: Sequence[float] = ()
    benchmark_curve: Sequence[float] = ()
    #: The execution model's own description. Printed verbatim — a result
    #: without its assumptions is a number without units.
    assumptions: Mapping[str, Any] = field(default_factory=dict)
    #: Caveats that qualify the whole report: synthetic ticks, short samples,
    #: unavailable data. Rendered prominently rather than in a footnote.
    caveats: Sequence[str] = ()

    def section(self, title: str, note: str = "") -> ReportSection:
        s = ReportSection(title=title, note=note)
        self.sections.append(s)
        return s

    def add(self, title: str, rows: Mapping[str, Any], note: str = "") -> ReportSection:
        s = self.section(title, note)
        s.rows = [(k, _fmt(v)) for k, v in rows.items()]
        return s


def _fmt(value: Any) -> str:
    """Format a value for display, keeping "unknown" distinct from zero."""
    if value is None:
        return "—"                     # never "0.00": unavailable is not zero
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:,.4f}".rstrip("0").rstrip(".") if abs(value) < 1000 else f"{value:,.2f}"
    return str(value)


# ═══════════════════════════════════════════════════ HTML

_CSS = """
:root{--bg:#0b0e14;--card:#141922;--ink:#e6e9ef;--muted:#8b94a7;--line:#232a36;
--pos:#3fb950;--neg:#f85149;--accent:#d4a72c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:940px;margin:0 auto;padding:32px 20px 64px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:15px;margin:28px 0 10px;
text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.sub{color:var(--muted);margin:0 0 20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:16px 18px;margin-bottom:14px}
table{width:100%;border-collapse:collapse}
td{padding:7px 0;border-bottom:1px solid var(--line)}
td:last-child{text-align:right;font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:none}
.note{color:var(--muted);font-size:12.5px;margin-top:10px}
.caveats{border-left:3px solid var(--accent);padding:12px 16px;background:#1a1710;
border-radius:0 8px 8px 0;margin-bottom:18px}
.caveats ul{margin:6px 0 0;padding-left:18px}.caveats li{margin:3px 0}
.assume{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.assume div{background:#0f141c;border:1px solid var(--line);border-radius:8px;padding:9px 11px}
.assume b{display:block;color:var(--muted);font-weight:500;font-size:11.5px;
text-transform:uppercase;letter-spacing:.05em}
svg{width:100%;height:auto;display:block}
footer{color:var(--muted);font-size:12px;margin-top:32px;border-top:1px solid var(--line);padding-top:14px}
@media (prefers-color-scheme:light){:root{--bg:#f6f7f9;--card:#fff;--ink:#11151c;
--muted:#5b6474;--line:#e3e7ee}.caveats{background:#fdf8e8}.assume div{background:#f9fafc}}
"""


def _curve_svg(curve: Sequence[float], benchmark: Sequence[float] = (),
               width: int = 880, height: int = 200) -> str:
    """An equity chart as inline SVG. No library, no external request."""
    if len(curve) < 2:
        return '<p class="note">No equity curve to draw.</p>'
    series = [("strategy", list(curve), "#3fb950")]
    if len(benchmark) >= 2:
        series.append(("benchmark", list(benchmark), "#8b94a7"))
    lo = min(min(s) for _n, s, _c in series)
    hi = max(max(s) for _n, s, _c in series)
    span = (hi - lo) or 1.0
    pad = 12

    paths = []
    for name, values, colour in series:
        step = (width - 2 * pad) / max(1, len(values) - 1)
        points = " ".join(
            f"{pad + i * step:.1f},{height - pad - ((v - lo) / span) * (height - 2 * pad):.1f}"
            for i, v in enumerate(values))
        dash = ' stroke-dasharray="4 3"' if name == "benchmark" else ""
        paths.append(f'<polyline fill="none" stroke="{colour}" stroke-width="1.8"'
                     f'{dash} points="{points}"/>')
    legend = " ".join(
        f'<tspan fill="{c}">■</tspan> {html.escape(n)}' for n, _s, c in series)
    return (f'<svg viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="equity curve">{"".join(paths)}'
            f'<text x="{pad}" y="14" font-size="11" fill="#8b94a7">{legend}</text>'
            f'</svg>')


def render_html(report: BacktestReport) -> str:
    """A self-contained HTML report — no CDN, no fonts, no scripts."""
    e = html.escape
    out = [f"<!doctype html><html><head><meta charset='utf-8'>",
           f"<meta name='viewport' content='width=device-width,initial-scale=1'>",
           f"<title>{e(report.title)}</title><style>{_CSS}</style></head><body>",
           "<div class='wrap'>", f"<h1>{e(report.title)}</h1>"]
    if report.subtitle:
        out.append(f"<p class='sub'>{e(report.subtitle)}</p>")

    if report.caveats:
        items = "".join(f"<li>{e(c)}</li>" for c in report.caveats)
        out.append("<div class='caveats'><strong>What qualifies these numbers"
                   f"</strong><ul>{items}</ul></div>")

    if len(report.equity_curve) >= 2:
        out.append("<h2>Equity</h2><div class='card'>"
                   + _curve_svg(report.equity_curve, report.benchmark_curve)
                   + "</div>")

    for section in report.sections:
        rows = "".join(f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>"
                       for k, v in section.rows)
        note = f"<p class='note'>{e(section.note)}</p>" if section.note else ""
        out.append(f"<h2>{e(section.title)}</h2><div class='card'>"
                   f"<table>{rows}</table>{note}</div>")

    if report.assumptions:
        cells = "".join(f"<div><b>{e(str(k).replace('_', ' '))}</b>{e(_fmt(v))}</div>"
                        for k, v in report.assumptions.items())
        out.append("<h2>Execution assumptions</h2><div class='card'>"
                   f"<div class='assume'>{cells}</div>"
                   "<p class='note'>A backtest result without its execution "
                   "assumptions is a number without units.</p></div>")

    out.append(f"<footer>Generated {report.generated_at.isoformat(timespec='seconds')}"
               " · Tradexa backtest report</footer></div></body></html>")
    return "".join(out)


# ═══════════════════════════════════════════════════ PDF

def _pdf_escape(text: str) -> str:
    """Escape for a PDF string literal, and drop anything outside Latin-1.

    The base-14 fonts are single-byte. A non-Latin-1 character would produce a
    corrupt file rather than a wrong glyph, so it is replaced — visibly, with
    '?', rather than silently dropped.
    """
    out = []
    for ch in text:
        if ch in "()\\":
            out.append("\\" + ch)
        elif 32 <= ord(ch) <= 255:
            out.append(ch)
        else:
            out.append("?")
    return "".join(out)


class _Pdf:
    """A minimal PDF 1.4 writer: pages, text, rules. Valid, not fancy."""

    WIDTH, HEIGHT = 595, 842          # A4 points
    MARGIN = 56

    def __init__(self) -> None:
        self._pages: list[list[str]] = []
        self._ops: list[str] = []
        self._y = self.HEIGHT - self.MARGIN

    # ------------------------------------------------------------ layout
    def _space(self, needed: float) -> None:
        if self._y - needed < self.MARGIN:
            self.page_break()

    def page_break(self) -> None:
        if self._ops:
            self._pages.append(self._ops)
        self._ops = []
        self._y = self.HEIGHT - self.MARGIN

    def text(self, value: str, *, size: float = 10, bold: bool = False,
             indent: float = 0, gap: float = 4) -> None:
        self._space(size + gap)
        font = "F2" if bold else "F1"
        self._ops.append(
            f"BT /{font} {size} Tf 1 0 0 1 {self.MARGIN + indent} {self._y:.1f} Tm "
            f"({_pdf_escape(value)}) Tj ET")
        self._y -= size + gap

    def row(self, left: str, right: str, *, size: float = 10) -> None:
        """A label/value line with the value right-aligned by estimation.

        Helvetica's average advance is ~0.5em; exact metrics would need the AFM
        tables, and being a point or two out on a right margin is not worth
        embedding a font metrics table to fix.
        """
        self._space(size + 4)
        x_right = self.WIDTH - self.MARGIN - len(right) * size * 0.5
        self._ops.append(
            f"BT /F1 {size} Tf 1 0 0 1 {self.MARGIN} {self._y:.1f} Tm "
            f"({_pdf_escape(left)}) Tj ET")
        self._ops.append(
            f"BT /F1 {size} Tf 1 0 0 1 {x_right:.1f} {self._y:.1f} Tm "
            f"({_pdf_escape(right)}) Tj ET")
        self._y -= size + 4

    def rule(self, *, gap: float = 8) -> None:
        self._space(gap * 2)
        self._y -= gap / 2
        self._ops.append(
            f"0.75 w 0.6 0.6 0.65 RG {self.MARGIN} {self._y:.1f} m "
            f"{self.WIDTH - self.MARGIN} {self._y:.1f} l S")
        self._y -= gap

    # ------------------------------------------------------------ output
    def build(self) -> bytes:
        self.page_break()
        objects: list[bytes] = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        font_regular = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                           b"/Encoding /WinAnsiEncoding >>")
        font_bold = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
                        b"/Encoding /WinAnsiEncoding >>")
        pages_id = len(objects) + 1 + 2 * len(self._pages) + 1

        page_ids: list[int] = []
        for ops in self._pages:
            stream = "\n".join(ops).encode("latin-1", "replace")
            # Flate-compressed: a 30-page report is ~5× smaller and every reader
            # since 1.2 handles it.
            packed = zlib.compress(stream)
            content_id = add(b"<< /Length " + str(len(packed)).encode()
                             + b" /Filter /FlateDecode >>\nstream\n" + packed
                             + b"\nendstream")
            page_ids.append(add(
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 "
                f"{self.WIDTH} {self.HEIGHT}] /Resources << /Font << /F1 "
                f"{font_regular} 0 R /F2 {font_bold} 0 R >> >> /Contents "
                f"{content_id} 0 R >>".encode()))

        kids = " ".join(f"{pid} 0 R" for pid in page_ids)
        add(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode())
        catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for index, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
        xref_at = len(out)
        out += f"xref\n0 {len(objects) + 1}\n".encode()
        out += b"0000000000 65535 f \n"
        for offset in offsets[1:]:
            out += f"{offset:010d} 00000 n \n".encode()
        out += (f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\n"
                f"startxref\n{xref_at}\n%%EOF\n").encode()
        return bytes(out)


def render_pdf(report: BacktestReport) -> bytes:
    """The same report as a PDF. Typographic, not graphical — see the module note."""
    pdf = _Pdf()
    pdf.text(report.title, size=18, bold=True, gap=6)
    if report.subtitle:
        pdf.text(report.subtitle, size=10, gap=2)
    pdf.text(f"Generated {report.generated_at.isoformat(timespec='seconds')}", size=8)
    pdf.rule()

    if report.caveats:
        pdf.text("What qualifies these numbers", size=11, bold=True)
        for caveat in report.caveats:
            # Wrapped by hand: a PDF has no line breaking, and a caveat running
            # off the page edge is a caveat nobody reads.
            for line in _wrap(f"- {caveat}", 92):
                pdf.text(line, size=9, indent=6, gap=2)
        pdf.rule()

    for section in report.sections:
        pdf.text(section.title, size=12, bold=True)
        for label, value in section.rows:
            pdf.row(label, value)
        if section.note:
            for line in _wrap(section.note, 96):
                pdf.text(line, size=8, gap=2)
        pdf.rule()

    if report.assumptions:
        pdf.text("Execution assumptions", size=12, bold=True)
        for key, value in report.assumptions.items():
            pdf.row(str(key).replace("_", " "), _fmt(value))
        pdf.text("A backtest result without its execution assumptions is a "
                 "number without units.", size=8)
    return pdf.build()


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines or [""]


__all__ = ["ReportSection", "BacktestReport", "render_html", "render_pdf"]
