"""Telegram messages written for a person: what to do first, then the levels, then one line of evidence.
Telegram HTML styling (bold / italic); every dynamic value is escaped. The full technical text is still stored."""
from __future__ import annotations

from html import escape

TRUST = {"VALIDATED": "🟢 Proven in a registered test", "LEAD (unproven)": "🟠 Promising, not proven",
         "NO EDGE": "🔴 No proven edge"}
TF_NAME = {"3": "3-min", "5": "5-min", "15": "15-min"}


def px(x: float | None) -> str:
    if x is None:
        return "–"
    return f"{x:,.1f}" if abs(x) >= 10000 else f"{x:,.2f}"      # indices 1 decimal, stocks and options 2


def e(x) -> str:
    return escape(str(x), quote=False)


def levels(side: int, entry: float, sl: float, t1: float, t2: float | None, t3: float | None) -> str:
    risk = abs(entry - sl)
    return (f"Entry <b>{px(entry)}</b>  ·  SL <b>{px(sl)}</b>  (risk {px(risk)})\n"
            f"Targets  <b>{px(t1)}</b>  →  <b>{px(t2)}</b>  →  <b>{px(t3)}</b>")


def signal(root: str, side: int, tf: str, when: str, entry: float, sl: float, t1, t2, t3, *, trust: str,
           evidence: str, chain: str, leg=None, leg_note: str = "", paper: str = "", range_pts: str = "",
           source: str = "", untested_tf: bool = False) -> str:
    arrow = "🟩 BUY" if side > 0 else "🟥 SELL"
    lines = [f"{arrow}  <b>{e(root)}</b>  ·  {TF_NAME.get(tf, e(tf) + 'm' if tf else '')}  ·  {e(when)}",
             "━━━━━━━━━━━━━━",
             "<b>Futures</b>",
             levels(side, entry, sl, t1, t2, t3)]
    if leg is not None and not leg.note:
        lines += ["", f"<b>Option</b>  buy <b>{leg.strike:g} {leg.typ}</b>  ({e(leg.expiry[8:10] + '/' + leg.expiry[5:7])})",
                  f"Entry <b>{px(leg.ask)}</b>  ·  SL <b>{px(leg.sl)}</b>",
                  f"Targets  <b>{px(leg.t1)}</b>  →  <b>{px(leg.t2)}</b>  →  <b>{px(leg.t3)}</b>",
                  "<i>option levels are estimates; exit when the futures trade exits</i>"]
    elif leg_note:
        lines += ["", f"<b>Option</b>  {e(leg_note)}"]
    lines += ["", f"<b>Track record</b>  {TRUST.get(trust, e(trust))}", f"<i>{e(evidence)}</i>"]
    if untested_tf:
        lines.append("⚠️ <i>3-minute signals have never been tested</i>")
    extra = [x for x in (chain, range_pts) if x]
    if extra:
        lines.append("  ·  ".join(e(x) for x in extra))
    if paper:
        lines.append(f"📒 {e(paper)}")
    lines.append(f"<i>{e(source + ' · ' if source else '')}paper signal · not advice · no order placed</i>")
    return "\n".join(lines)


def closed(root: str, side: int, book: str, reason: str, r: float, inr: float | None) -> str:
    icon = "✅" if r > 0 else "⛔" if r < 0 else "➖"
    what = {"executable": "Paper trade", "theoretical": "Model trade", "r4": "Range-target trade"}.get(book, "Paper trade")
    money = f"  ({'+' if inr >= 0 else '−'}₹{abs(inr):,.0f})" if inr is not None else ""
    return (f"{icon} <b>{e(root)} {'BUY' if side > 0 else 'SELL'}</b> closed — {e(reason)}\n"
            f"{what}: <b>{r:+.2f}R</b>{money} after costs")


def watch_line(sym: str, chg: float, rvol, last: float, high, low) -> str:
    tags = [f"{chg * 100:+.1f}%"]
    if rvol is not None and rvol == rvol:
        tags.append(f"vol {rvol:.1f}×")
    rng = f"  ·  day {px(low)}–{px(high)}" if high and low else ""
    return f"• <b>{e(sym)}</b>  {e('  ·  '.join(tags))}  ·  now {px(last)}{rng}"


def stock_pick(sym: str, side: int, chg: float | None, rvol: float | None, entry: float, R: float, leg=None,
               leg_note: str = "", paper: str = "", score: float | None = None) -> str:
    arrow = "🟩 BUY" if side > 0 else "🟥 SELL"
    tags = []
    if chg is not None:
        tags.append(f"{chg * 100:+.1f}%")
    if rvol is not None and rvol == rvol:
        tags.append(f"vol {rvol:.1f}×")
    if score is not None:
        tags.append(f"score {score:.0f}")
    sl = entry - side * R
    t = [entry + side * k * R for k in (1, 2, 3)]
    out = [f"{arrow} <b>{e(sym)}</b>  {e('  ·  '.join(tags))}",
           f"   Entry <b>{px(entry)}</b> · SL <b>{px(sl)}</b> · T <b>{px(t[0])}</b> → {px(t[1])} → {px(t[2])}"]
    if leg is not None and not leg.note:
        out.append(f"   Option {leg.strike:g} {leg.typ} @ <b>{px(leg.ask)}</b> · SL {px(leg.sl)} · T {px(leg.t1)}")
    elif leg_note:
        out.append(f"   Option: {e(leg_note)}")
    if paper:
        out.append(f"   📒 {e(paper)}")
    return "\n".join(out)


def paper_words(note: str, side: int) -> str:
    """' | paper fut entry 1,052.15 | 24950CE ...' -> 'paper: future bought at 1,052.15'."""
    parts = [p.strip() for p in note.split("|") if p.strip()]
    for p in parts:
        if p.startswith("paper fut entry") or p.startswith("paper fut "):
            return f"paper: future {'bought' if side > 0 else 'sold'} at {p.split()[-1]}"
    for p in parts:
        if p.startswith("paper:"):
            return "paper: not entered (" + p[len("paper:"):].strip() + ")"
    return ""
