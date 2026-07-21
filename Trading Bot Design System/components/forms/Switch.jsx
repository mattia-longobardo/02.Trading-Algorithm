import React from 'react';
export function Switch({ checked = false, onChange, label, ...rest }) {
  const btn = <button type="button" role="switch" aria-checked={checked} className="ds-switch" onClick={() => onChange && onChange(!checked)} {...rest}></button>;
  if (!label) return btn;
  return <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 14, cursor: 'pointer' }}>{btn}{label}</label>;
}