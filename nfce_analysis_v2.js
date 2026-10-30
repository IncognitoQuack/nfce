// NFCE v2 backtest analysis — runs on the TradingView tab after the v2 strategy's Pine Logs were scraped into
// window.__runs2 = { "NIFTY_5": {"NFCE|META": "...", "NFCE|V|0": "...", ...}, ... }  (see PHASE7_V2_EVIDENCE.md).
// V line : NFCE|V|idx|abl|scoreOff|rvMult|brkIdx|reqV|n|trade;trade;...
// trade  : entryMinuteUTC,side,score,expiry,entry,R,pnlPts(40/30/30 weighted, gross),exitCode,barsHeld,orders
// Costs  : the dated schedule of nfce_engine/nfce/costs.py (STT, NSE charge, SEBI, stamp, GST, Rs 20/order), 10 lots,
//          plus 4 ticks friction per side. "current" = the 18 Oct 2026 schedule applied to every trade (stress).
// The port is checked against costs.py's reference values by selfTest() (Rs 966.2155 for NIFTY 25000 x 65).
(function () {
  const FUT_STT = [['1900-01-01', 0.000100], ['2023-04-01', 0.000125], ['2024-10-01', 0.000200], ['2026-04-01', 0.000500]];
  const FUT_EXCH = [['1900-01-01', 0.0000190], ['2024-10-01', 0.0000173], ['2026-03-01', 0.0000183]];
  const SEBI = 0.000001, STAMP = 0.00002, GST = 0.18, CURRENT = '2026-10-18', LOTS = 10, FRICTION_TICKS = 4;
  const rate = (tab, d) => { let r = tab[0][1]; for (const [k, v] of tab) if (d >= k) r = v; return r; };
  function fees(entry, exit, side, units, d, orders) {
    const [b, s] = side > 0 ? [entry, exit] : [exit, entry];
    const bv = b * units, sv = s * units, brk = 20 * orders;
    const stt = rate(FUT_STT, d) * sv, ex = rate(FUT_EXCH, d) * (bv + sv), sebi = SEBI * (bv + sv);
    return stt + ex + sebi + STAMP * bv + brk + GST * (brk + ex + sebi);
  }
  function selfTest() {
    const a = fees(25000, 25000, 1, 65, CURRENT, 2), b = fees(55000, 55000, 1, 30, CURRENT, 2);
    return Math.abs(a - 966.2155) < 0.01 && Math.abs(b - 980.3542) < 0.01;
  }
  const ABL = ['Volume', 'Directional', 'Trend stack', 'ADX/DMI', 'HTF', 'CVD', 'Futures OI', 'Heavyweights', 'India VIX', 'Vol hard filter'];
  function meta(run) {
    const m = {}; run['NFCE|META'].split('|').slice(2).forEach((kv, i) => {
      if (i === 0) m.sym = kv; else if (i === 1) m.tf = kv; else { const [k, v] = kv.split('='); m[k] = v; } });
    m.mintick = +m.mintick; m.pv = +m.pv; return m;
  }
  function istDate(tMin) { return new Date(tMin * 60000 + 330 * 60000).toISOString().slice(0, 10); }
  function parseVar(line, m) {
    const p = line.split('|');
    const v = { idx: +p[2], abl: +p[3], so: +p[4], rm: +p[5], bi: +p[6], reqV: p[7] === '1', trades: [] };
    (p[9] || '').split(';').filter(Boolean).forEach(t => {
      const f = t.split(','), side = f[1] === 'L' ? 1 : -1, e = +f[4], pnl = +f[6], R = +f[5], orders = +(f[9] || 2);
      const d = istDate(+f[0]), units = m.pv * LOTS, fr = 2 * FRICTION_TICKS * m.mintick, ax = e + side * pnl;
      const cD = fees(e, ax, side, units, d, orders) / units + fr, cC = fees(e, ax, side, units, CURRENT, orders) / units + fr;
      v.trades.push({ d, side, sc: +f[2], exp: f[3] === '1', e, R, pnl, ex: f[7], bars: +f[8], orders,
        rG: pnl / R, rD: (pnl - cD) / R, rC: (pnl - cC) / R, inrD: (pnl - cD) * units });
    });
    return v;
  }
  function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }
  function dayBoot(tr, key, B = 2000) {
    const g = {}; tr.forEach(t => (g[t.d] = g[t.d] || []).push(t[key])); const G = Object.values(g); if (G.length < 2) return [NaN, NaN];
    const r = rng(7), ms = [];
    for (let b = 0; b < B; b++) { let s = 0, n = 0; for (let k = 0; k < G.length; k++) { const x = G[Math.floor(r() * G.length)]; for (const y of x) { s += y; n++; } } ms.push(s / n); }
    ms.sort((a, b) => a - b); return [ms[Math.floor(0.025 * B)], ms[Math.floor(0.975 * B)]];
  }
  function stats(tr, boot) {
    const n = tr.length; if (!n) return { n: 0 };
    const mean = k => tr.reduce((s, t) => s + t[k], 0) / n;
    const mD = mean('rD'), sd = Math.sqrt(tr.reduce((s, t) => s + (t.rD - mD) ** 2, 0) / Math.max(n - 1, 1));
    let eq = 0, pk = 0, dd = 0, gw = 0, gl = 0; tr.forEach(t => { eq += t.inrD; pk = Math.max(pk, eq); dd = Math.max(dd, pk - eq); t.inrD > 0 ? gw += t.inrD : gl -= t.inrD; });
    const o = { n, days: new Set(tr.map(t => t.d)).size, win: tr.filter(t => t.rD > 0).length / n, rG: mean('rG'), rD: mD, rC: mean('rC'),
      t: sd > 0 ? mD / (sd / Math.sqrt(n)) : 0, pf: gl > 0 ? gw / gl : Infinity, net: eq, dd };
    if (boot) { o.bootD = dayBoot(tr, 'rD'); o.bootC = dayBoot(tr, 'rC'); }
    return o;
  }
  const f = (x, k = 3) => (x === undefined || Number.isNaN(x)) ? 'na' : (+x).toFixed(k);
  const out = { selfTest: selfTest(), runs: {} };
  for (const [key, run] of Object.entries(window.__runs2 || {})) {
    const m = meta(run);
    const vars = Object.entries(run).filter(([k]) => k.startsWith('NFCE|V|')).map(([, l]) => parseVar(l, m)).sort((a, b) => a.idx - b.idx);
    const base = vars.find(v => v.idx === 0), sb = stats(base.trades, true);
    const abl = vars.filter(v => v.abl >= 0).map(v => { const s = stats(v.trades); return { f: ABL[v.abl], n: s.n, rD: s.rD, dR: s.n ? s.rD - sb.rD : NaN }; });
    const grid = vars.filter(v => v.abl === -2).map(v => ({ so: v.so, rm: v.rm, bi: v.bi, ...stats(v.trades) }));
    const gp = grid.filter(g => g.n >= 10);
    out.runs[key] = { m, base: sb, abl, grid: { cells: grid.length, withN10: gp.length, positiveNet: gp.filter(g => g.rD > 0).length,
      best: gp.slice().sort((a, b) => b.rD - a.rD)[0], worst: gp.slice().sort((a, b) => a.rD - b.rD)[0] } };
  }
  out.text = Object.entries(out.runs).map(([k, r]) => {
    const b = r.base, m = r.m;
    return `${k} ${m.t0 ? istDate(+m.t0) : ''}..${m.t1 ? istDate(+m.t1) : ''} bars=${m.bars} mm=${m.mmStateFlat}/${m.mmEmuFlat}/${m.mmQty} instr=${m.instr}\n` +
      ` base n=${b.n} days=${b.days} win=${f(b.win * 100, 1)}% R gross=${f(b.rG)} dated=${f(b.rD)} [${f(b.bootD[0])},${f(b.bootD[1])}] current=${f(b.rC)} [${f(b.bootC[0])},${f(b.bootC[1])}] t=${f(b.t, 2)} PF=${f(b.pf, 2)} net=${f(b.net / 1e5, 2)}L dd=${f(b.dd / 1e5, 2)}L\n` +
      ` abl ${r.abl.map(a => `${a.f}:${a.n}/${f(a.dR, 2)}`).join(' ')}\n` +
      ` grid ${r.grid.positiveNet}/${r.grid.withN10} cells(n>=10) net>0; best so=${r.grid.best?.so} rm=${r.grid.best?.rm} bi=${r.grid.best?.bi} n=${r.grid.best?.n} R=${f(r.grid.best?.rD)}; worst R=${f(r.grid.worst?.rD)}`;
  }).join('\n');
  window.__an2 = out;
  return out.selfTest + '\n' + out.text;
})();
