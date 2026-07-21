import React from 'react';
export function Stamp({ tone = 'neutral', children, style, className = '' }) {
  return <span className={'ds-stamp ds-stamp--' + tone + ' ' + className} style={style}>{children}</span>;
}