import type { Metadata } from "next";
import { Geist_Mono, Instrument_Sans, Newsreader } from "next/font/google";
import "./globals.css";

import { Providers } from "@/components/providers";
import { AppFrame } from "@/components/app-frame";
import { UserMenu } from "@/components/user-menu";

const instrumentSans = Instrument_Sans({
  variable: "--font-instrument-sans",
  subsets: ["latin"],
});

const newsreader = Newsreader({
  variable: "--font-newsreader",
  subsets: ["latin"],
  weight: ["400", "500"],
  style: ["normal", "italic"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "Trading Bot",
    template: "%s · Trading Bot",
  },
  description: "Dashboard operativa del Trading Bot.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="it"
      suppressHydrationWarning
      className={`${instrumentSans.variable} ${newsreader.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full">
        <Providers>
          <AppFrame userSlot={<UserMenu />}>{children}</AppFrame>
        </Providers>
      </body>
    </html>
  );
}
