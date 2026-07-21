import React from 'react';
export function SidebarNav({ items = [], activeId, onSelect, style }) {
  return (
    <nav className="ds-sidebar" style={style}>
      <div style={{ padding: '16px 16px 12px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 500, fontSize: 14, letterSpacing: '.08em', textTransform: 'uppercase' }}>Trading Bot</div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '.18em', textTransform: 'uppercase', color: 'var(--muted-foreground)', marginTop: 2 }}>Swing trading</div>
      </div>
      <div style={{ padding: '12px 0', flex: 1 }}>
        {items.map((it) => (
          <a key={it.id} href="#" onClick={(e) => { e.preventDefault(); onSelect && onSelect(it.id); }}
            className={'ds-sidebar__item' + (it.id === activeId ? ' ds-sidebar__item--active' : '')}>
            {it.icon}{it.label}
          </a>
        ))}
      </div>
    </nav>
  );
}
