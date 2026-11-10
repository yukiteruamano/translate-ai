"use client";

import { apiUrl } from "@/lib/api";
import { useLanguages } from "@/lib/useLanguages";

/** Link to the Swagger UI; hidden while the server reports `/docs` as disabled. */
export default function ApiLink() {
  const { languages } = useLanguages();
  if (!languages?.docs_enabled) return null;
  return (
    <a
      href={apiUrl("/docs")}
      className="inline-flex h-9 items-center rounded-lg px-2.5 text-sm font-medium text-slate-500 transition hover:bg-slate-900/[0.05] hover:text-slate-900 active:scale-95 dark:text-slate-400 dark:hover:bg-white/[0.06] dark:hover:text-slate-100"
    >
      API
    </a>
  );
}
