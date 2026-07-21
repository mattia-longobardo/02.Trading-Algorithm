import React from 'react';
export function Select({ label, id, options = [], className = '', ...rest }) {
  const sel = <select id={id} className={'ds-select ' + className} {...rest}>{options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select>;
  if (!label) return sel;
  return <div><label className="ds-label" htmlFor={id}>{label}</label>{sel}</div>;
}