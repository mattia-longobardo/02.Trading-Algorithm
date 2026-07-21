/** Striscia strumenti sticky 48px: timbri ambiente/modalità a sinistra, sicurezza + prossima run a destra. Con environment="real" appare il banner rosso persistente. */
export interface AppHeaderProps {
  /** demo = timbro cobalto · real = timbro pieno rosso + banner */
  environment?: 'demo' | 'real';
  mode?: 'dry-run' | 'live';
  killSwitch?: 'ok' | 'triggered';
  breaker?: 'ok' | 'triggered';
  /** Data/ora mono, es. "2026-07-21 09:30" */
  nextRun?: string;
  /** Slot sinistro (toggle sidebar) */
  left?: React.ReactNode;
  /** Slot destro (toggle tema) */
  right?: React.ReactNode;
}
export declare function AppHeader(props: AppHeaderProps): JSX.Element;