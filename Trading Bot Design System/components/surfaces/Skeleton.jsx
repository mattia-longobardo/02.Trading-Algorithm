import React from 'react';
export function Skeleton({ width = '100%', height = 14, style }) {
  return <div className="ds-skeleton" style={{ width, height, ...style }}></div>;
}