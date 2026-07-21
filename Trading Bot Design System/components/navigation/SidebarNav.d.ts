/** Sidebar bianca, hairline a destra. Voce attiva: testo cobalto + regola verticale 2px a sinistra (niente pill). In fondo il claim in Newsreader corsivo. */
export interface SidebarNavItem {
  id: string;
  label: string;
  /** Icona lucide, strokeWidth 1.5 */
  icon?: React.ReactNode;
}
export interface SidebarNavProps {
  items: SidebarNavItem[];
  activeId?: string;
  onSelect?: (id: string) => void;
  style?: React.CSSProperties;
}
export declare function SidebarNav(props: SidebarNavProps): JSX.Element;