/** Tabella stile estratto conto: solo hairline orizzontali, header mono uppercase, numeri mono right-aligned (align:'right'). Stati nelle celle via <Stamp>. */
export interface TableColumn {
  key: string;
  label: string;
  /** 'right' per colonne numeriche: mono tabular right-aligned */
  align?: 'left' | 'right';
}
export interface TableProps {
  columns: TableColumn[];
  /** Le celle possono essere React node (es. <Stamp>) */
  rows: Record<string, React.ReactNode>[];
  rowKey?: string;
  style?: React.CSSProperties;
}
export declare function Table(props: TableProps): JSX.Element;