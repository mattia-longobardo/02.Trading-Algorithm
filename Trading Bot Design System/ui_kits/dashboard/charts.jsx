const { Card } = window.EToroBotDesignSystem_9cb9fa;

function Icon({ name, size = 16 }) {
  const ref = React.useRef(null);
  React.useEffect(() => {
    if (!ref.current || !window.lucide) return;
    ref.current.innerHTML = '';
    const el = window.lucide.createElement(window.lucide[name]);
    el.setAttribute('width', size); el.setAttribute('height', size);
    el.setAttribute('stroke-width', '1.5');
    ref.current.appendChild(el);
  }, [name, size]);
  return <span ref={ref} style={{ display: 'inline-flex', width: size, height: size, flex: 'none' }}></span>;
}

function EquityChart({ height = 220 }) {
  // serie fittizie: bot, SPY lump-sum, SPY cash-flow matched
  const W = 920, H = height, pad = { l: 56, r: 12, t: 10, b: 24 };
  const n = 40;
  const mk = (drift, vol, seed) => { let v = 10000, out = []; for (let i = 0; i < n; i++) { v *= 1 + drift + vol * Math.sin(seed * 3 + i * 0.9) * (0.4 + ((i * seed * 7919) % 10) / 14); out.push(v); } return out; };
  const bot = mk(0.006, 0.008, 1.3), spy = mk(0.0035, 0.005, 2.1), spycf = mk(0.003, 0.004, 3.7);
  const all = [...bot, ...spy, ...spycf];
  const min = Math.min(...all) * 0.99, max = Math.max(...all) * 1.01;
  const x = (i) => pad.l + (i / (n - 1)) * (W - pad.l - pad.r);
  const y = (v) => pad.t + (1 - (v - min) / (max - min)) * (H - pad.t - pad.b);
  const path = (s) => s.map((v, i) => (i ? 'L' : 'M') + x(i).toFixed(1) + ',' + y(v).toFixed(1)).join(' ');
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => min + f * (max - min));
  const fmt = (v) => (v / 1000).toFixed(1) + 'k';
  return (
    <div>
      <svg viewBox={'0 0 ' + W + ' ' + H} style={{ width: '100%', display: 'block' }}>
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke="var(--border)" />
            <text x={pad.l - 8} y={y(t) + 3} textAnchor="end" style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fill: 'var(--muted-foreground)' }}>{fmt(t)}</text>
          </g>
        ))}
        <path d={path(spy)} fill="none" stroke="var(--benchmark)" strokeWidth="1.5" strokeDasharray="6 4" />
        <path d={path(spycf)} fill="none" stroke="var(--benchmark-alt)" strokeWidth="1.5" strokeDasharray="2 3" />
        <path d={path(bot)} fill="none" stroke="var(--primary)" strokeWidth="1.5" />
      </svg>
      <div style={{ display: 'flex', gap: 20, marginTop: 8, fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--muted-foreground)' }}>
        <span style={{ color: 'var(--primary)' }}>— Bot</span><span>- - SPY lump-sum</span><span>·· SPY cash-flow matched</span>
      </div>
    </div>
  );
}

function RiskGauge({ value = 4 }) {
  const bands = [
    { to: 3, c: 'var(--positive)', l: 'basso' },
    { to: 6, c: 'var(--caution)', l: 'medio' },
    { to: 8, c: 'var(--risk-high)', l: 'alto' },
    { to: 10, c: 'var(--negative)', l: 'estremo' },
  ];
  const band = bands.find((b) => value <= b.to);
  return (
    <div>
      <div style={{ display: 'flex', gap: 2 }}>
        {Array.from({ length: 10 }, (_, i) => {
          const b = bands.find((bb) => i + 1 <= bb.to);
          return <div key={i} style={{ flex: 1, height: 10, borderRadius: 2, background: i < value ? b.c : 'var(--muted)', border: '1px solid var(--border)' }}></div>;
        })}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, alignItems: 'baseline' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: 22, fontVariantNumeric: 'tabular-nums' }}>{value}<span style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>/10</span></span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.08em', color: band.c }}>{band.l}</span>
      </div>
    </div>
  );
}

function SectorDonut() {
  const data = [
    { l: 'Tech', v: 34, c: 'var(--chart-1)' }, { l: 'Energia', v: 22, c: 'var(--chart-2)' },
    { l: 'Salute', v: 18, c: 'var(--chart-3)' }, { l: 'Finanza', v: 15, c: 'var(--chart-4)' }, { l: 'Altro', v: 11, c: 'var(--chart-5)' },
  ];
  const R = 46, r = 30, C = 2 * Math.PI * ((R + r) / 2);
  let acc = 0;
  return (
    <div style={{ display: 'flex', gap: 20, alignItems: 'center' }}>
      <svg width="110" height="110" viewBox="0 0 110 110">
        {data.map((d, i) => {
          const frac = d.v / 100, dash = frac * C;
          const el = <circle key={i} cx="55" cy="55" r={(R + r) / 2} fill="none" stroke={d.c} strokeWidth={R - r}
            strokeDasharray={(dash - 2) + ' ' + (C - dash + 2)} strokeDashoffset={-acc * C + C / 4} />;
          acc += frac; return el;
        })}
      </svg>
      <div style={{ display: 'grid', gap: 4, flex: 1 }}>
        {data.map((d) => (
          <div key={d.l} style={{ display: 'flex', alignItems: 'center', gap: 8, borderBottom: '1px solid var(--border)', paddingBottom: 4 }}>
            <span style={{ width: 8, height: 8, background: d.c, flex: 'none' }}></span>
            <span style={{ fontSize: 13, flex: 1 }}>{d.l}</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontVariantNumeric: 'tabular-nums' }}>{d.v}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function MonthlyHeatmap() {
  const months = ['Gen', 'Feb', 'Mar', 'Apr', 'Mag', 'Giu', 'Lug'];
  const vals = [1.8, -0.6, 3.2, 0.4, -1.9, 2.6, 1.1];
  return (
    <div style={{ display: 'flex', gap: 2 }}>
      {months.map((m, i) => {
        const v = vals[i];
        const a = Math.min(42, 8 + Math.abs(v) * 10);
        const bg = v === 0 ? 'var(--card)' : 'color-mix(in srgb, var(--' + (v > 0 ? 'positive' : 'negative') + ') ' + a + '%, var(--card))';
        return (
          <div key={m} style={{ flex: 1, border: '1px solid var(--border)', background: bg, padding: '8px 4px', textAlign: 'center' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--muted-foreground)' }}>{m}</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontVariantNumeric: 'tabular-nums', marginTop: 2 }}>{v > 0 ? '+' : v < 0 ? '−' : ''}{Math.abs(v).toFixed(1)}%</div>
          </div>
        );
      })}
    </div>
  );
}

Object.assign(window, { Icon, EquityChart, RiskGauge, SectorDonut, MonthlyHeatmap });