/** AlertDialog per azioni irreversibili. Il passaggio a live richiede la digitazione esatta di "VOGLIO ANDARE LIVE". */
export interface DialogProps {
  open: boolean;
  title?: string;
  description?: string;
  children?: React.ReactNode;
  /** Bottoni, allineati a destra */
  footer?: React.ReactNode;
  onClose?: () => void;
}
export declare function Dialog(props: DialogProps): JSX.Element | null;