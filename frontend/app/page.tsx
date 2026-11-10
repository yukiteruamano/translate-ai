import Link from "next/link";
import ApiLink from "@/components/ApiLink";
import Translator from "@/components/Translator";
import ThemeToggle from "@/components/ThemeToggle";
import Logo from "@/components/Logo";

const UI_SOURCE = "https://github.com/sioaeko/NLLB_translator";
// Avisos de licencia de terceros: los sirve la API desde /licenses (ver Dockerfile).
const FOOTER_LINK =
  "w-fit underline-offset-4 transition hover:text-slate-900 hover:underline dark:hover:text-slate-200";

export default function Home() {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="mx-auto flex w-full max-w-4xl items-center justify-between px-4 pt-4 sm:px-6 sm:pt-6">
        <Link href="/" className="-m-1 flex items-center gap-2.5 rounded-lg p-1">
          <Logo size={30} />
          <span className="text-[15px] font-semibold tracking-tight">Traductor NLLB</span>
        </Link>
        <div className="flex items-center gap-0.5">
          <ApiLink />
          <ThemeToggle />
        </div>
      </header>

      <main className="mx-auto w-full max-w-4xl flex-1 px-4 pb-16 sm:px-6">
        <div className="pb-5 pt-7 sm:pb-7 sm:pt-12">
          <h1 className="text-[1.75rem] font-semibold leading-[1.1] tracking-[-0.025em] sm:text-[2.5rem]">
            Del español a{" "}
            <span className="text-accent-600 dark:text-accent-400">cinco idiomas.</span>
          </h1>
          <p className="mt-2.5 max-w-[56ch] text-[15px] leading-relaxed text-slate-600 dark:text-slate-400">
            Inglés, portugués, alemán, francés e italiano con NLLB-200. El modelo se ejecuta en este
            servidor: el texto no se envía a terceros.
          </p>
        </div>

        <Translator />
      </main>

      <footer className="mx-auto flex w-full max-w-4xl flex-col gap-1 px-4 pb-8 text-xs text-slate-500 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <span>
          Modelo NLLB-200 de Meta, licencia CC-BY-NC 4.0: solo para pruebas hasta validar su uso
          comercial.
        </span>
        <span className="flex flex-wrap gap-x-3 gap-y-1">
          <a href={UI_SOURCE} target="_blank" rel="noopener noreferrer" className={FOOTER_LINK}>
            Interfaz basada en NLLB_translator
          </a>
          <a
            href="/licenses/NLLB_translator-MIT.txt"
            target="_blank"
            rel="noopener noreferrer"
            className={FOOTER_LINK}
          >
            Licencia MIT
          </a>
          <a
            href="/licenses/Geist-OFL-1.1.txt"
            target="_blank"
            rel="noopener noreferrer"
            className={FOOTER_LINK}
          >
            Fuente Geist (OFL)
          </a>
        </span>
      </footer>
    </div>
  );
}
