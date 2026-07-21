/** Campo testo: bordo input, radius 4px, focus ring cobalto, etichetta sans 13px opzionale. */
export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
}
export declare function Input(props: InputProps): JSX.Element;