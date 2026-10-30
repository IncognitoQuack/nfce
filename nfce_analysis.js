// NFCE backtest analysis — runs in the browser console on the TradingView tab after the
// strategy's Pine Logs have been scraped into window.__runs = { "NIFTY_5": {"NFCE|META": "...", "NFCE|V|0": "...", ...}, ... }.
// Each V line: NFCE|V|idx|abl|scoreOff|rvMult|brkIdx|reqV|n|trade;trade;...
// Each trade : entryMinuteUTC,side,score,expiry,entry,R,pnlPts(40/30/30 weighted, gross),exitCode,barsHeld
// Costs (report Section 3): 0.03% of notional per side (STT+exchange+stamp+brokerage+GST ~0.06% round trip)
// + 4 ticks slippage per side. Applied to every trade.
(function () {
  const COMM_SIDE = 0.0003, SLIP_TICKS = 4;
  const ABL = ['Volume', 'Directional', 'Trend stack', 'ADX/DMI', 'HTF', 'CVD', 'Futures OI', 'Heavyweights', 'India VIX'];
  function meta(run) {
    const m = {}; run['NFCE|META'].split('|').slice(2).forEach((kv, i) => { if (i === 0) m.sym = kv; else if (i === 1) m.tf = kv; else { const [k, v] = kv.split('='); m[k] = v; } });
    m.mintick = +m.mintick; m.pv = +m.pv; return m;
  }
  function parseVar(line) {
    const p = line.split('|');
    const v = { idx: +p[2], abl: +p[3], so: +p[4], rm: +p[5], bi: +p[6], reqV: p[7] === '1', trades: [] };
    (p[9] || '').split(';').filter(Boolean).forEach(t => {
      const f = t.split(',');
      v.trades.push({ tMin: +f[0], side: f[1], sc: +f[2], exp: f[3] === '1', e: +f[4], R: +f[5], pnl: +f[6], ex: f[7], bars: +f[8] });
    });
    return v;
  }
  function istParts(tMin) { const d = new Date(tMin * 60000 + 330 * 60000); return { ym: d.toISOString().slice(0, 7), hh: d.getUTCHours(), date: d.toISOString().slice(0, 10) }; }
  function stats(trades, m) {
    const n = trades.length; if (!n) return { n: 0 };
    let eq = 0, peak = 0, dd = 0, gw = 0, gl = 0, wins = 0, sR = 0, sRg = 0, sR2 = 0, gross = 0;
    trades.forEach(t => {
      const cost = COMM_SIDE * 2 * t.e + 2 * SLIP_TICKS * m.mintick;
      const net = t.pnl - cost; t.net = net; t.rNet = net / t.R;
      const inr = net * m.pv; gross += t.pnl * m.pv;
      eq += inr; peak = Math.max(peak, eq); dd = Math.max(dd, peak - eq);
      if (inr > 0) { gw += inr; wins++; } else gl -= inr;
      sR += t.rNet; sRg += t.pnl / t.R; sR2 += t.rNet * t.rNet;
    });
    const mean = sR / n, sd = Math.sqrt(Math.max(sR2 / n - mean * mean, 0) * n / Math.max(n - 1, 1));
    return { n, win: wins / n, avgRg: sRg / n, avgR: mean, t: sd > 0 ? mean / (sd / Math.sqrt(n)) : 0, pf: gl > 0 ? gw / gl : Infinity, dd, net: eq, gross };
  }
  const out = {};
  for (const [key, run] of Object.entries(window.__runs)) {
    const m = meta(run);
    const vars = Object.entries(run).filter(([k]) => k.startsWith('NFCE|V|')).map(([, l]) => parseVar(l)).sort((a, b) => a.idx - b.idx);
    out[key] = { m, vars: vars.map(v => ({ ...v, s: stats(v.trades, m) })) };
  }
  window.__an = out; window.__ABL = ABL;
  return Object.keys(out);
})();
