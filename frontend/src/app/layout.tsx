import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";
import { AppProviders } from "@/lib/providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "Trading Console",
  description: "Console di amministrazione del trading bot",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="it">
      <body className="font-sans antialiased">
        <AppProviders>
          <AppShell>{children}</AppShell>
        </AppProviders>
      </body>
    </html>
  );
}
