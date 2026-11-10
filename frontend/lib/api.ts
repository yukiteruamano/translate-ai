import type { LanguagesResponse, TranslateResponse } from "./types";

// Same-origin by default (single-container deploy); override for split dev/prod.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "http://localhost:8000";

// The server answers 503 + Retry-After when all its translation slots are taken.
const BUSY_STATUS = 503;
const MAX_BUSY_RETRIES = 2;
const DEFAULT_RETRY_SECONDS = 5;
const MAX_RETRY_SECONDS = 10;

/** Absolute URL of a server path (same-origin in the single-container deploy). */
export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

async function loadLanguages(): Promise<LanguagesResponse> {
  const res = await fetch(apiUrl("/api/languages"));
  if (!res.ok) throw new Error("No se pudieron cargar los idiomas");
  return (await res.json()) as LanguagesResponse;
}

// Shared by every component that needs it; a failure is not remembered, so callers can retry.
let languagesRequest: Promise<LanguagesResponse> | null = null;

export function fetchLanguages(): Promise<LanguagesResponse> {
  languagesRequest ??= loadLanguages().catch((error) => {
    languagesRequest = null;
    throw error;
  });
  return languagesRequest;
}

async function checkResponse(res: Response) {
  if (res.ok) return;
  const detail = await res
    .json()
    .then((data) => data.detail)
    .catch(() => null);
  throw new Error(typeof detail === "string" ? detail : `La traducción ha fallado (${res.status})`);
}

function retryDelayMs(res: Response): number {
  const seconds = Number(res.headers.get("Retry-After"));
  const wanted = Number.isFinite(seconds) && seconds > 0 ? seconds : DEFAULT_RETRY_SECONDS;
  return Math.min(wanted, MAX_RETRY_SECONDS) * 1000;
}

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(signal.reason);
    const onAbort = () => {
      clearTimeout(timer);
      reject(signal?.reason);
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/** POST to the stream endpoint, waiting out a "server busy" answer a couple of times. */
async function openStream(body: string, signal?: AbortSignal): Promise<Response> {
  for (let attempt = 0; ; attempt++) {
    const res = await fetch(apiUrl("/api/translate/stream"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      signal,
    });
    if (res.status !== BUSY_STATUS || attempt >= MAX_BUSY_RETRIES) {
      await checkResponse(res);
      return res;
    }
    await res.body?.cancel().catch(() => {});
    await wait(retryDelayMs(res), signal);
  }
}

/** Display generated text as it arrives; only a done event marks a complete result. */
export async function translateStream(
  text: string,
  source: string,
  target: string,
  onDelta: (text: string) => void,
  signal?: AbortSignal
): Promise<TranslateResponse> {
  const res = await openStream(JSON.stringify({ text, source, target }), signal);
  if (!res.body) throw new Error("La respuesta está vacía. Inténtalo de nuevo.");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  function readEvent(line: string): TranslateResponse | undefined {
    signal?.throwIfAborted();
    if (!line.trim()) return;
    let event;
    try {
      event = JSON.parse(line);
    } catch {
      throw new Error("La respuesta del servidor no es válida. Inténtalo de nuevo.");
    }
    if (event?.type === "delta" && typeof event.text === "string") {
      if (event.text) onDelta(event.text);
      return;
    }
    if (
      event?.type === "done" &&
      typeof event.translation === "string" &&
      typeof event.source === "string" &&
      typeof event.target === "string"
    ) {
      return { translation: event.translation, source: event.source, target: event.target };
    }
    if (event?.type === "error") {
      throw new Error(
        typeof event.detail === "string"
          ? event.detail
          : "La traducción ha fallado. Inténtalo de nuevo."
      );
    }
    throw new Error("La respuesta del servidor no es válida. Inténtalo de nuevo.");
  }

  try {
    while (true) {
      const { done, value } = await reader.read();
      signal?.throwIfAborted();
      buffer += decoder.decode(value, { stream: !done });
      let newline;
      while ((newline = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, newline);
        buffer = buffer.slice(newline + 1);
        const result = readEvent(line);
        if (result) return result;
      }
      if (done) {
        const result = readEvent(buffer);
        if (result) return result;
        throw new Error("La traducción se interrumpió antes de terminar. Inténtalo de nuevo.");
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
