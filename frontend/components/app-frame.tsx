"use client";

import { usePathname } from "next/navigation";

import { AppSidebar } from "@/components/app-sidebar";
import { RealEnvironmentBanner, SiteHeader } from "@/components/site-header";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";

export function AppFrame({
  children,
  userSlot,
}: {
  children: React.ReactNode;
  userSlot: React.ReactNode;
}) {
  const pathname = usePathname();

  if (pathname === "/login") return <>{children}</>;

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <RealEnvironmentBanner />
        <SiteHeader userSlot={userSlot} />
        <main className="mx-auto w-full max-w-[1200px] flex-1 px-4 py-6 md:px-8">
          {children}
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}
