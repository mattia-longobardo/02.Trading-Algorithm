"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BrainIcon,
  FileChartColumnIcon,
  GaugeIcon,
  HistoryIcon,
  LayoutDashboardIcon,
  LineChartIcon,
  ReceiptTextIcon,
  SettingsIcon,
} from "lucide-react";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboardIcon },
  { href: "/trades", label: "Trade", icon: ReceiptTextIcon },
  { href: "/history", label: "Storico", icon: HistoryIcon },
  { href: "/benchmark", label: "Benchmark", icon: LineChartIcon },
  { href: "/reports", label: "Report", icon: FileChartColumnIcon },
  { href: "/risk", label: "Rischio", icon: GaugeIcon },
  { href: "/knowledge", label: "Knowledge Base", icon: BrainIcon },
  { href: "/settings", label: "Impostazioni", icon: SettingsIcon },
] as const;

export function AppSidebar() {
  const pathname = usePathname();

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <Sidebar collapsible="icon" className="border-r">
      <SidebarHeader className="px-4 pt-5 pb-3 group-data-[collapsible=icon]:px-2">
        <Link href="/" className="block group-data-[collapsible=icon]:hidden">
          <span className="text-foreground font-mono text-[11px] font-medium tracking-[0.18em] uppercase">
            Trading Bot
          </span>
          <span className="text-muted-foreground mt-0.5 block font-mono text-[10px] tracking-[0.08em] uppercase">
            Registro operativo
          </span>
        </Link>
        <Link
          href="/"
          className="bg-primary hidden size-8 items-center justify-center rounded-md font-mono text-xs font-semibold text-white group-data-[collapsible=icon]:flex dark:text-[#141517]"
          aria-label="Dashboard"
        >
          TB
        </Link>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel className="text-muted-foreground px-4 font-mono text-[10px] tracking-[0.18em] uppercase">
            Registro
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu className="gap-0.5">
              {NAV_ITEMS.map((item) => {
                const active = isActive(item.href);
                return (
                  <SidebarMenuItem key={item.href}>
                    <SidebarMenuButton
                      asChild
                      isActive={active}
                      tooltip={item.label}
                      className="text-muted-foreground hover:text-foreground relative h-8 rounded-none px-4 text-[13px] transition-colors before:absolute before:inset-y-1 before:left-0 before:w-0.5 before:bg-transparent data-[active=true]:bg-transparent data-[active=true]:font-medium data-[active=true]:text-primary data-[active=true]:before:bg-primary hover:bg-accent/60 group-data-[collapsible=icon]:px-2"
                    >
                      <Link href={item.href}>
                        <item.icon strokeWidth={1.5} />
                        <span>{item.label}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="px-4 pb-4" />
    </Sidebar>
  );
}
