/** Pallino 6px + etichetta mono per lo stato dei sistemi di sicurezza nell'header. Mai solo colore: l'etichetta è obbligatoria. */
export interface DotIndicatorProps {
  /** ok = verde (sistema a posto) · triggered = rosso (attivo/scattato) */
  status?: 'ok' | 'triggered';
  label: string;
  style?: React.CSSProperties;
}
export declare function DotIndicator(props: DotIndicatorProps): JSX.Element;