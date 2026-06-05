import {
  Activity,
  ClipboardList,
  FileText,
  Globe,
  LineChart,
  Settings,
  Sparkles,
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
  { href: "/orders", label: "Ordini", icon: ClipboardList },
  { href: "/console", label: "Console", icon: Terminal },
  { href: "/universe", label: "Universe", icon: Globe },
  { href: "/reports", label: "Report", icon: FileText },
  { href: "/prompts", label: "Prompt", icon: Sparkles, adminOnly: true },
  { href: "/logs", label: "Log", icon: Activity },
  { href: "/settings", label: "Impostazioni", icon: Settings },
];

export function visibleNavFor(role: UserRole): NavItem[] {
  return NAV.filter((item) => !item.adminOnly || role === "admin");
}
