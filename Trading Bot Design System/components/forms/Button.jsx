import React from 'react';
export function Button({ variant = 'secondary', children, className = '', ...rest }) {
  return <button className={'ds-btn ds-btn--' + variant + ' ' + className} {...rest}>{children}</button>;
}