import React from 'react';
export function Input({ label, id, className = '', ...rest }) {
  const input = <input id={id} className={'ds-input ' + className} {...rest} />;
  if (!label) return input;
  return <div><label className="ds-label" htmlFor={id}>{label}</label>{input}</div>;
}