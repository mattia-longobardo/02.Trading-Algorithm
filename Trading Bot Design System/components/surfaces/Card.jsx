import React from 'react';
export function Card({ title, description, action, children, style, className = '', bodyStyle }) {
  return (
    <div className={'ds-card ' + className} style={style}>
      {(title || action) && (
        <div className="ds-card__header">
          <div>{title && <div className="ds-card__title">{title}</div>}{description && <div className="ds-card__desc">{description}</div>}</div>
          {action}
        </div>
      )}
      <div className="ds-card__body" style={bodyStyle}>{children}</div>
    </div>
  );
}