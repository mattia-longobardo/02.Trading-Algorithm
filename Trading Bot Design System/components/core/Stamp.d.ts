/**
 * Il timbro di verdetto — la firma del sistema. Ogni stato dell'app è un timbro.
 * @startingPoint section="Core" subtitle="Timbro di verdetto — la firma del sistema" viewport="700x220"
 */
export interface StampProps {
  /** approved=APPROVATO/FILLED · rejected=RESPINTO · neutral=DRY-RUN/SKIPPED · caution=LIVE · accent=DEMO · solid-danger=REALE/KILL SWITCH · solid-caution=trip breaker */
  tone?: 'approved' | 'rejected' | 'neutral' | 'caution' | 'accent' | 'solid-danger' | 'solid-caution';
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}
export declare function Stamp(props: StampProps): JSX.Element;