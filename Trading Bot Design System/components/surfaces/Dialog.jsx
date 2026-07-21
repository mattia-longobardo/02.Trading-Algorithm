import React from 'react';
export function Dialog({ open, title, description, children, footer, onClose }) {
  if (!open) return null;
  return (
    <div className="ds-dialog-overlay" onClick={(e) => { if (e.target === e.currentTarget && onClose) onClose(); }}>
      <div className="ds-dialog" role="alertdialog" aria-modal="true">
        {title && <div className="ds-card__title">{title}</div>}
        {description && <div className="ds-card__desc" style={{ marginTop: 4 }}>{description}</div>}
        {children && <div style={{ marginTop: 16 }}>{children}</div>}
        {footer && <div style={{ marginTop: 20, display: 'flex', justifyContent: 'flex-end', gap: 8 }}>{footer}</div>}
      </div>
    </div>
  );
}