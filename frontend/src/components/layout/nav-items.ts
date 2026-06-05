import {
  Activity,
  ClipboardList,
  FileText,
  Globe,
  LineChart,
  Settings,
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
  { href: "/positions", label: "Posizioni", icon: Activity },
  { href: "/trades", label: "Trade", icon: ClipboardList },
  { href: "/ops", label: "Operazioni", icon: Terminal },
  { href: "/universe", label: "Universe", icon: Globe },
  { href: "/reports", label: "Report", icon: FileText },
  { href: "/admin", label: "Amministrazione", icon: Settings },
];

export function visibleNavFor(role: UserRole): NavItem[] {
  return NAV.filter((item) => !item.adminOnly || role === "admin");
}
