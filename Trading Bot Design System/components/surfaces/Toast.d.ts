/** Toast: card bianca hairline. Gli errori portano il dettaglio concreto dal backend, mai generici. */
export interface ToastProps {
  title: string;
  description?: string;
  tone?: 'neutral' | 'success' | 'error';
  style?: React.CSSProperties;
}
export declare function Toast(props: ToastProps): JSX.Element;