/**
 * Bottone. Una sola azione primaria per vista; il distruttivo richiede sempre conferma via Dialog.
 * @startingPoint section="Forms" subtitle="Primario, secondario, ghost, distruttivo" viewport="700x230"
 */
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** primary = unica azione principale ("Esegui run ora") · secondary = azioni normali · ghost = in tabella/nav · destructive = KILL SWITCH (tinta negative 10%) */
  variant?: 'primary' | 'secondary' | 'ghost' | 'destructive';
}
export declare function Button(props: ButtonProps): JSX.Element;