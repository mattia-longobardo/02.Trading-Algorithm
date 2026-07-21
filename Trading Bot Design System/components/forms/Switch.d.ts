/** Interruttore rettangolare (niente pill — forma da registro). Controllato: checked + onChange. */
export interface SwitchProps {
  checked?: boolean;
  onChange?: (checked: boolean) => void;
  label?: string;
}
export declare function Switch(props: SwitchProps): JSX.Element;