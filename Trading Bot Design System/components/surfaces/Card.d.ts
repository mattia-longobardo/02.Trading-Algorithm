/**
 * Card bianca, hairline, radius 6px, shadow-xs, padding 24px.
 * @startingPoint section="Surfaces" subtitle="Superficie base con header opzionale" viewport="700x260"
 */
export interface CardProps {
  title?: string;
  /** 13px muted, sotto il titolo */
  description?: string;
  /** Azione in alto a destra, es. link "Tutte →" */
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
  bodyStyle?: React.CSSProperties;
}
export declare function Card(props: CardProps): JSX.Element;