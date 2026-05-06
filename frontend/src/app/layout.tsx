import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Trading Dashboard",
  description: "Dashboard del trading bot",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="it">
      <body className="font-mono antialiased">
        <header className="border-b border-(--color-line) bg-(--color-panel)/80 backdrop-blur">
          <nav className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-4">
            <Link href="/" className="text-lg font-semibold text-(--color-text)">
              Trading Dashboard
            </Link>
            <div className="flex gap-4 text-sm text-(--color-muted)">
              <Link href="/" className="hover:text-(--color-text)">
                Home
              </Link>
              <Link href="/logs" className="hover:text-(--color-text)">
                Logs
              </Link>
            </div>
          </nav>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
