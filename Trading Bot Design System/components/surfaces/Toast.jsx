import React from 'react';
export function Toast({ title, description, tone = 'neutral', style }) {
  const c = tone === 'error' ? 'var(--negative)' : tone === 'success' ? 'var(--positive)' : 'var(--foreground)';
  return (
    <div className="ds-toast" style={style}>
      <div style={{ fontSize: 14, fontWeight: 600, color: c }}>{title}</div>
      {description && <div style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>{description}</div>}
    </div>
  );
}