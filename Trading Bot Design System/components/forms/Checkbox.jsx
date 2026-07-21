import React from 'react';
export function Checkbox({ label, ...rest }) {
  return <label className="ds-checkbox"><input type="checkbox" {...rest} />{label}</label>;
}