import type { Metadata, Viewport } from "next";
// Fuentes del paquete `geist` (autoalojadas): el build no necesita acceso a Google Fonts.
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import "./globals.css";

export const metadata: Metadata = {
  title: "Traductor NLLB — español a inglés, portugués, alemán, francés e italiano",
  description:
    "Traducción del español a cinco idiomas con NLLB-200 (600M), ejecutada en CPU en tu propio servidor.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#F6F7F9" },
    { media: "(prefers-color-scheme: dark)", color: "#0A0E14" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="es"
      suppressHydrationWarning
      className={`${GeistSans.variable} ${GeistMono.variable}`}
    >
      <head>
        {/* Apply saved / system theme before paint to avoid a flash. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('theme');if(t==='dark'||(!t&&window.matchMedia('(prefers-color-scheme: dark)').matches)){document.documentElement.classList.add('dark');}}catch(e){}})();`,
          }}
        />
      </head>
      <body className="min-h-dvh bg-canvas font-sans text-slate-900 antialiased dark:bg-canvas-dark dark:text-slate-100">
        {children}
      </body>
    </html>
  );
}
