import React from 'react';
export function DotIndicator({ status = 'ok', label, style }) {
  const color = status === 'ok' ? 'var(--positive)' : 'var(--negative)';
  return <span className="ds-dot" style={style}><span className="ds-dot__dot" style={{ background: color }}></span>{label}</span>;
}