"use client";

import { useEffect, useState } from "react";
import { fetchLanguages } from "./api";
import type { LanguagesResponse } from "./types";

const RETRY_MS = 5000;

/** Languages reported by the server; keeps retrying while it is unreachable. */
export function useLanguages(): { languages: LanguagesResponse | null; offline: boolean } {
  const [languages, setLanguages] = useState<LanguagesResponse | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = () => {
      fetchLanguages()
        .then((value) => {
          if (cancelled) return;
          setLanguages(value);
          setOffline(false);
        })
        .catch(() => {
          if (cancelled) return;
          setOffline(true);
          timer = setTimeout(load, RETRY_MS);
        });
    };
    load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  return { languages, offline };
}
