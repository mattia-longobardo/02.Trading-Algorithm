/** Select nativa con lo stesso trattamento dell'Input. */
export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  options?: { value: string; label: string }[];
}
export declare function Select(props: SelectProps): JSX.Element;