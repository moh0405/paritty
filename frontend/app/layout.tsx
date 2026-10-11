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
  title: "Paritty",
  description: "Continuous clean-to-lock copilot for clinical trials",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col"><Providers>
          <a href="#main-content" className="fixed left-4 top-2 z-[100] -translate-y-[160%] rounded-lg bg-white px-4 py-2.5 font-semibold text-cyan-800 shadow-xl transition-transform focus:translate-y-0 focus:outline-3 focus:outline-cyan-500">Skip to main content</a>
          <Header />
          <div className="flex flex-1">
            {/* usePathname() is request-time data on dynamic routes: without a boundary it blocks their prerendering */}
            <Suspense fallback={null}><Sidebar /></Suspense>
            <div id="main-content" tabIndex={-1} className="min-w-0 flex-1 pb-20 outline-none md:pb-0">{children}</div>
          </div>
          <Suspense fallback={null}><Tour /></Suspense>
        </Providers>
      </body>
    </html>
  );
}
