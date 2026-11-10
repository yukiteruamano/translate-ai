export interface Language {
  code: string;
  name: string;
}

export interface LanguagesResponse {
  source: Language;
  targets: Language[];
  max_input_chars: number;
  docs_enabled: boolean;
}

export interface TranslateResponse {
  translation: string;
  source: string;
  target: string;
}
