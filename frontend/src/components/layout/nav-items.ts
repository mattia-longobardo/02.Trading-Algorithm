import {
  Activity,
  ClipboardList,
  FileText,
  Globe,
  LineChart,
  Scale,
  Settings,
  ShieldAlert,
  Terminal,
} from "lucide-react";
import type { ComponentType } from "react";
import type { UserRole } from "@/lib/types";

export interface NavItem {
  href: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  adminOnly?: boolean;
}

export const NAV: NavItem[] = [
  { href: "/", label: "Dashboard", icon: LineChart },
  { href: "/benchmark", label: "Benchmark", icon: Scale },
  { href: "/positions", label: "Posizioni", icon: Activity },
  { href: "/risk", label: "Rischio", icon: ShieldAlert },
  { href: "/trades", label: "Trade", icon: ClipboardList },
  { href: "/ops", label: "Operazioni", icon: Terminal },
  { href: "/universe", label: "Universe", icon: Globe },
  { href: "/reports", label: "Report", icon: FileText },
  { href: "/admin", label: "Amministrazione", icon: Settings },
];

export function visibleNavFor(role: UserRole): NavItem[] {
  return NAV.filter((item) => !item.adminOnly || role === "admin");
}

/** Routes shown directly in the phone bottom tab bar (in this order). */
export const MOBILE_PRIMARY: readonly string[] = ["/", "/positions", "/trades"];

/** Primary nav items (bottom-bar tabs) from a role-filtered list. */
export function primaryNav(items: NavItem[]): NavItem[] {
  return MOBILE_PRIMARY.map((href) => items.find((i) => i.href === href)).filter(
    (i): i is NavItem => Boolean(i)
  );
}

/** Secondary nav items (shown under the "Altro" sheet). */
export function secondaryNav(items: NavItem[]): NavItem[] {
  return items.filter((i) => !MOBILE_PRIMARY.includes(i.href));
}
