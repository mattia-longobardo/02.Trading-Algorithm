import React from 'react';
import { Stamp } from '../core/Stamp.jsx';
import { DotIndicator } from '../core/DotIndicator.jsx';
export function AppHeader({ environment = 'demo', mode = 'dry-run', killSwitch = 'ok', breaker = 'ok', nextRun, left, right }) {
  const real = environment === 'real';
  return (
    <div style={{ position: 'sticky', top: 0, zIndex: 40 }}>
      <div className="ds-header" style={{ position: 'static' }}>
        {left}
        <Stamp tone={real ? 'solid-danger' : 'accent'}>{real ? 'Reale' : 'Demo'}</Stamp>
        <Stamp tone={mode === 'live' ? 'caution' : 'neutral'}>{mode === 'live' ? 'Live' : 'Dry-run'}</Stamp>
        <div style={{ flex: 1 }}></div>
        <DotIndicator status={killSwitch === 'ok' ? 'ok' : 'triggered'} label="Kill switch" />
        <DotIndicator status={breaker === 'ok' ? 'ok' : 'triggered'} label="Breaker" />
        {nextRun && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--muted-foreground)', fontVariantNumeric: 'tabular-nums' }}>Prossima run {nextRun}</span>}
        {right}
      </div>
      {real && <div className="ds-banner-real">Conto reale — gli ordini muovono denaro vero</div>}
    </div>
  );
}