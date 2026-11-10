"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { translateStream } from "@/lib/api";
import { clipText, copyText } from "@/lib/text";
import { useLanguages } from "@/lib/useLanguages";

// Used until /api/languages reports the server's real MAX_INPUT_CHARS.
const DEFAULT_MAX_CHARS = 50_000;
const DEBOUNCE_MS = 500;
const SLOW_MS = 2500;
const CACHE_SIZE = 32;
const COPY_FEEDBACK_MS = 1500;
const MODEL_LABEL = "NLLB-200 · 600M";

const SAMPLES = [
  "¿Cómo puedo comprar bitcoin de forma segura?",
  "Me encantaría visitar Berlín algún día.",
  "El mercado cierra la semana con subidas moderadas.",
];

interface TranslationRequest {
  text: string;
  source: string;
  target: string;
  cacheKey: string;
}

const iconProps = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

const ghostBtn =
  "inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium text-slate-600 transition hover:bg-slate-900/[0.05] hover:text-slate-900 active:scale-[0.97] dark:text-slate-400 dark:hover:bg-white/[0.06] dark:hover:text-slate-100";

export default function Translator() {
  const { languages, offline } = useLanguages();
  const [target, setTarget] = useState("en");
  const [input, setInput] = useState("");
  const [output, setOutput] = useState("");
  const [outputFor, setOutputFor] = useState<TranslationRequest | null>(null);
  const [loading, setLoading] = useState(false);
  const [slow, setSlow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const [clipped, setClipped] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const currentRequestRef = useRef<TranslationRequest | null>(null);
  const cacheRef = useRef(new Map<string, string>());
  const taRef = useRef<HTMLTextAreaElement>(null);

  const source = languages?.source ?? null;
  const targets = languages?.targets ?? [];
  const reportedMax = languages?.max_input_chars ?? 0;
  const maxChars =
    Number.isInteger(reportedMax) && reportedMax > 0 ? reportedMax : DEFAULT_MAX_CHARS;
  const sourceCode = source?.code ?? "";
  const request = useMemo<TranslationRequest>(
    () => ({
      text: input,
      source: sourceCode,
      target,
      cacheKey: JSON.stringify([input, sourceCode, target]),
    }),
    [input, sourceCode, target]
  );

  const runTranslate = useCallback(async (next: TranslationRequest) => {
    if (currentRequestRef.current !== next) return;
    abortRef.current?.abort();
    abortRef.current = null;
    const { text, source: src, target: tgt, cacheKey } = next;
    setError(null);
    setCopied(false);
    setSlow(false);
    setOutputFor(next);
    if (!text.trim() || !src) {
      setOutput("");
      setLoading(false);
      return;
    }

    const cached = cacheRef.current.get(cacheKey);
    if (cached !== undefined) {
      cacheRef.current.delete(cacheKey);
      cacheRef.current.set(cacheKey, cached);
      setOutput(cached);
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;
    const isCurrent = () =>
      !controller.signal.aborted &&
      abortRef.current === controller &&
      currentRequestRef.current === next;
    setOutput("");
    setLoading(true);
    let partial = "";
    try {
      const res = await translateStream(
        text,
        src,
        tgt,
        (delta) => {
          if (!isCurrent()) return;
          partial += delta;
          setOutput(partial);
        },
        controller.signal
      );
      if (!isCurrent()) return;
      setOutput(res.translation);
      cacheRef.current.set(cacheKey, res.translation);
      if (cacheRef.current.size > CACHE_SIZE) {
        cacheRef.current.delete(cacheRef.current.keys().next().value!);
      }
    } catch (e) {
      if (isCurrent() && (e as Error).name !== "AbortError") {
        setError((e as Error).message);
        setOutput("");
      }
    } finally {
      if (isCurrent()) {
        abortRef.current = null;
        setLoading(false);
      }
    }
  }, []);

  useLayoutEffect(() => {
    currentRequestRef.current = request;
    setLoading(false);
    setError(null);
    setCopied(false);
    // Invalidate the running request on every edit, before waiting for typing to stop.
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (!request.text.trim() || !request.source || cacheRef.current.has(request.cacheKey)) {
      void runTranslate(request);
    } else {
      timer = setTimeout(() => void runTranslate(request), DEBOUNCE_MS);
    }
    return () => {
      clearTimeout(timer);
      currentRequestRef.current = null;
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, [request, runTranslate]);

  // Only surface the "still working" note when a request takes a while.
  useEffect(() => {
    if (!loading) {
      setSlow(false);
      return;
    }
    const id = setTimeout(() => setSlow(true), SLOW_MS);
    return () => clearTimeout(id);
  }, [loading]);

  // Grow the textarea with its content; CSS caps the height.
  const fit = useCallback(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${ta.scrollHeight}px`;
  }, []);
  useLayoutEffect(fit, [input, fit]);
  useEffect(() => {
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [fit]);

  useEffect(() => () => clearTimeout(copyTimerRef.current), []);

  async function copyOutput() {
    if (!output) return;
    const ok = await copyText(output);
    setCopied(ok);
    setCopyFailed(!ok);
    clearTimeout(copyTimerRef.current);
    copyTimerRef.current = setTimeout(() => {
      setCopied(false);
      setCopyFailed(false);
    }, COPY_FEEDBACK_MS);
  }

  function changeInput(value: string) {
    setClipped(value.length > maxChars);
    setInput(clipText(value, maxChars));
  }

  // Between an edit and the debounced request, the shown translation belongs to
  // older input: dim it rather than let it pass for the current result.
  const hasInput = !!input.trim();
  const stale = !!output && outputFor !== request;

  let result: React.ReactNode;
  if (error) {
    result = (
      <div className="text-[15px]">
        <p className="flex items-start gap-2 text-red-600 dark:text-red-400">
          <svg className="mt-0.5 h-[18px] w-[18px] shrink-0" {...iconProps}>
            <circle cx="12" cy="12" r="9" />
            <path d="M12 8v4.5M12 16h.01" />
          </svg>
          <span>{error}</span>
        </p>
        <button
          type="button"
          onClick={() => runTranslate(request)}
          className="mt-2.5 font-medium text-accent-600 underline-offset-4 hover:underline dark:text-accent-400"
        >
          Reintentar
        </button>
      </div>
    );
  } else if (hasInput && loading && !output) {
    result = (
      <div>
        <span className="sr-only">Traduciendo</span>
        <div className="space-y-3 pt-1.5" aria-hidden="true">
          <div className="skeleton h-3.5 w-11/12 rounded-full" />
          <div className="skeleton h-3.5 w-3/4 rounded-full" />
          <div className="skeleton h-3.5 w-2/5 rounded-full" />
        </div>
        {slow && (
          <p className="mt-5 text-sm text-slate-500 dark:text-slate-400">
            Los textos largos se traducen por partes: la primera aparecerá en cuanto esté lista.
          </p>
        )}
      </div>
    );
  } else if (hasInput && output) {
    result = (
      <p
        lang={target}
        data-stale={stale}
        className={`whitespace-pre-wrap transition-opacity duration-200 ${stale ? "opacity-45" : ""}`}
      >
        {output}
      </p>
    );
  } else {
    result = <p className="text-slate-400 dark:text-slate-500">Traducción</p>;
  }

  return (
    <div className="w-full">
      <section
        aria-label="Traductor"
        className="relative rounded-2xl border border-slate-900/[0.08] bg-white shadow-[0_1px_2px_rgb(15_23_42/0.04),0_16px_40px_-22px_rgb(15_23_42/0.22)] transition-[border-color] duration-200 focus-within:border-accent-300 dark:border-white/[0.08] dark:bg-surface-dark dark:shadow-[0_16px_40px_-22px_rgb(0_0_0/0.9)] dark:focus-within:border-accent-800"
      >
        {/* top progress bar */}
        <div
          className={`pointer-events-none absolute inset-x-0 top-0 h-0.5 overflow-hidden rounded-t-2xl transition-opacity ${loading ? "opacity-100" : "opacity-0"}`}
        >
          <div className="h-full w-1/3 animate-loading bg-accent-500" />
        </div>

        <div className="grid overflow-hidden rounded-2xl md:grid-cols-2">
          {/* Input */}
          <div
            className="flex min-h-[9.5rem] cursor-text flex-col md:min-h-[18rem]"
            onClick={(e) => {
              if (e.target === e.currentTarget) taRef.current?.focus();
            }}
          >
            <div className="flex h-12 items-center border-b border-slate-900/[0.06] px-4 text-[15px] font-medium text-slate-800 sm:px-5 dark:border-white/[0.06] dark:text-slate-100">
              {source?.name ?? (
                <span className="skeleton inline-block h-3 w-16 rounded-full" aria-hidden="true" />
              )}
            </div>
            <label htmlFor="source-text" className="sr-only">
              Texto a traducir
            </label>
            <textarea
              id="source-text"
              ref={taRef}
              rows={3}
              value={input}
              lang={sourceCode || "es"}
              onChange={(e) => changeInput(e.target.value)}
              placeholder="Escribe o pega el texto a traducir"
              className="scroll-thin block max-h-[55vh] w-full resize-none overflow-y-auto bg-transparent px-4 pt-4 text-[17px] leading-relaxed outline-none placeholder:text-slate-400 sm:px-5 md:text-lg dark:placeholder:text-slate-500"
            />
            {!input && (
              <div className="flex flex-wrap items-center gap-1.5 px-4 pb-1 pt-3 sm:px-5">
                <span className="mr-0.5 text-xs text-slate-500 dark:text-slate-400">Prueba</span>
                {SAMPLES.map((text) => (
                  <button
                    key={text}
                    type="button"
                    onClick={() => {
                      changeInput(text);
                      taRef.current?.focus();
                    }}
                    className="inline-flex max-w-full items-center rounded-lg border border-slate-900/[0.08] px-2 py-1 text-[13px] text-slate-700 transition hover:border-accent-300 hover:bg-accent-50 hover:text-accent-800 active:scale-[0.97] dark:border-white/10 dark:text-slate-300 dark:hover:border-accent-800 dark:hover:bg-accent-950/50 dark:hover:text-accent-100"
                  >
                    <span className="truncate" lang="es">
                      {text}
                    </span>
                  </button>
                ))}
              </div>
            )}
            <div className="mt-auto flex h-12 items-center justify-between px-2 sm:px-3">
              {input ? (
                <button
                  type="button"
                  onClick={() => {
                    changeInput("");
                    taRef.current?.focus();
                  }}
                  className={ghostBtn}
                >
                  <svg className="h-3.5 w-3.5" {...iconProps}>
                    <path d="M6 18 18 6M6 6l12 12" />
                  </svg>
                  Borrar
                </button>
              ) : (
                <span />
              )}
              <span className="flex items-center gap-2 px-2 text-xs">
                {clipped && (
                  <span role="status" className="text-red-500">
                    Texto recortado al máximo permitido
                  </span>
                )}
                <span
                  className={`tabular-nums ${input.length >= maxChars ? "text-red-500" : "text-slate-400 dark:text-slate-500"}`}
                >
                  {input.length.toLocaleString("es-ES")} / {maxChars.toLocaleString("es-ES")}
                </span>
              </span>
            </div>
          </div>

          {/* Output */}
          <div className="flex min-h-[9.5rem] flex-col border-t border-slate-900/[0.06] bg-slate-900/[0.02] md:min-h-[18rem] md:border-l md:border-t-0 dark:border-white/[0.06] dark:bg-white/[0.02]">
            <fieldset className="flex h-12 items-center gap-1 overflow-x-auto border-b border-slate-900/[0.06] px-2 sm:px-3 dark:border-white/[0.06]">
              <legend className="sr-only">Idioma de destino</legend>
              {targets.length === 0 && (
                <span
                  className="skeleton ml-2 inline-block h-3 w-40 rounded-full"
                  aria-hidden="true"
                />
              )}
              {targets.map((l) => (
                <label key={l.code} className="shrink-0 cursor-pointer">
                  <input
                    type="radio"
                    name="target"
                    value={l.code}
                    checked={target === l.code}
                    onChange={() => setTarget(l.code)}
                    className="peer sr-only"
                  />
                  <span className="inline-flex h-8 items-center rounded-lg px-2.5 text-sm font-medium text-slate-600 transition hover:bg-slate-900/[0.05] peer-checked:bg-accent-500/10 peer-checked:text-accent-700 peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-accent-500 dark:text-slate-400 dark:hover:bg-white/[0.06] dark:peer-checked:bg-accent-500/20 dark:peer-checked:text-accent-300">
                    {l.name}
                  </span>
                </label>
              ))}
            </fieldset>
            {/* aria-busy: el lector de pantalla anuncia el resultado entero al terminar, no cada trozo. */}
            <div
              aria-live="polite"
              aria-busy={loading}
              className="flex-1 px-4 pt-4 text-[17px] leading-relaxed sm:px-5 md:text-lg"
            >
              {result}
            </div>
            <div className="flex h-12 items-center justify-between px-2 sm:px-3">
              <span className="flex min-w-0 items-center gap-1.5 px-2 text-xs text-slate-500 dark:text-slate-400">
                {hasInput && output && !error && !stale && (
                  <>
                    <span className="truncate">{MODEL_LABEL}</span>
                    {loading && (
                      <span className="shrink-0" role="status">
                        · Traduciendo…
                      </span>
                    )}
                  </>
                )}
              </span>
              <button
                type="button"
                onClick={copyOutput}
                disabled={!hasInput || !output || !!error || stale}
                className={`${ghostBtn} disabled:pointer-events-none disabled:opacity-0`}
              >
                {copied ? (
                  <svg className="h-3.5 w-3.5 text-accent-600 dark:text-accent-400" {...iconProps}>
                    <path d="M4.5 12.75l6 6 9-13.5" />
                  </svg>
                ) : (
                  <svg className="h-3.5 w-3.5" {...iconProps}>
                    <rect x="8" y="8" width="12" height="12" rx="2" />
                    <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" />
                  </svg>
                )}
                {copied ? "Copiado" : copyFailed ? "No se pudo copiar" : "Copiar"}
              </button>
            </div>
          </div>
        </div>
      </section>

      {offline && (
        <div className="mt-3 flex items-start gap-2.5 rounded-xl border border-slate-900/[0.08] bg-white px-4 py-3 text-sm text-slate-600 dark:border-white/10 dark:bg-surface-dark dark:text-slate-400">
          <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-red-500" aria-hidden="true" />
          <span>No se puede contactar con el servidor de traducción. Reintentando…</span>
        </div>
      )}
    </div>
  );
}
