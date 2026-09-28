import type { Metadata } from "next";
import "./globals.css";
import { Nav } from "@/components/Nav";

export const metadata: Metadata = {
  title: "Highlights",
  description: "Sports highlights manager",
};

const themeScript = `
  (function() {
    try {
      const savedTheme = localStorage.getItem('theme');
      const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      const theme = savedTheme || (systemPrefersDark ? 'dark' : 'light');
      document.documentElement.setAttribute('data-theme', theme);
    } catch (e) {}
  })();
`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className="min-h-screen"
        style={{ backgroundColor: "var(--bg)", color: "var(--text)" }}
      >
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        <header
          className="sticky top-0 z-10 border-b backdrop-blur"
          style={{
            backgroundColor: "var(--bg-elevated)",
            borderColor: "var(--border)",
          }}
        >
          <Nav />
        </header>
        <main className="w-full px-4 py-6 sm:px-6">{children}</main>
      </body>
    </html>
  );
}
