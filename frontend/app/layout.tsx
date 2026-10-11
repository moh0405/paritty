import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Suspense } from "react";
import "./globals.css";
import { Providers } from "@/components/Providers";
import { Header } from "@/components/Header";
import { Sidebar } from "@/components/Sidebar";
import { Tour } from "@/components/Tour";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "LockStep",
  description: "Continuous clean-to-lock copilot for clinical trials",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col"><Providers>
          <Header />
          <div className="flex flex-1">
            {/* usePathname() is request-time data on dynamic routes: without a boundary it blocks their prerendering */}
            <Suspense fallback={null}><Sidebar /></Suspense>
            <div className="min-w-0 flex-1">{children}</div>
          </div>
          <Suspense fallback={null}><Tour /></Suspense>
        </Providers>
      </body>
    </html>
  );
}
