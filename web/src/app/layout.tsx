import type { Metadata } from "next";
import "./globals.css";
import { Nav } from "@/components/Nav";

export const metadata: Metadata = {
  title: "Highlights",
  description: "Sports highlights manager",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <header className="sticky top-0 z-10 border-b border-white/10 bg-[#0b0f17]/90 backdrop-blur">
          <Nav />
        </header>
        <main className="w-full px-4 py-6 sm:px-6">{children}</main>
      </body>
    </html>
  );
}
