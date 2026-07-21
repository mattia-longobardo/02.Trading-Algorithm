import React from 'react';
export function Table({ columns = [], rows = [], rowKey, style }) {
  return (
    <table className="ds-table" style={style}>
      <thead><tr>{columns.map((c) => <th key={c.key} className={c.align === 'right' ? 'num' : ''}>{c.label}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => (
        <tr key={rowKey ? r[rowKey] : i}>{columns.map((c) => <td key={c.key} className={c.align === 'right' ? 'num' : ''}>{r[c.key]}</td>)}</tr>
      ))}</tbody>
    </table>
  );
}