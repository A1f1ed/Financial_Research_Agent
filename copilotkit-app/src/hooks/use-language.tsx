"use client";

import { createContext, useCallback, useContext, useState } from "react";
import translations from "@/lib/ui-translations.json";
import { UI_TRANSLATION_PATTERNS } from "@/lib/ui-translation-patterns";

export type Language = "zh" | "en";
export type Translate = <T>(text: T) => T;
const catalog: Record<string, string> = translations;
const patterns = UI_TRANSLATION_PATTERNS.map(([source, target]) => ({
  regex: new RegExp("^" + source.split(/\{\d+\}/).map(part => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("(.*?)") + "$"), target,
}));

export function translateUI(text: string, language: Language): string {
  if (language !== "en") return text;
  const known = catalog[text.trim()];
  if (known !== undefined) return text.replace(text.trim(), known);
  for (const { regex, target } of patterns) {
    const match = text.match(regex);
    if (match) return target.replace(/\{(\d+)\}/g, (_, index: string) => translateUI(match[Number(index) + 1], language));
  }
  return text;
}
const LanguageContext = createContext<{ language: Language; setLanguage: (language: Language) => void }>({ language: "en", setLanguage: () => {} });

export function LanguageProvider({ initialLanguage, children }: { initialLanguage: Language; children: React.ReactNode }) {
  const [language, updateLanguage] = useState(initialLanguage);
  const setLanguage = useCallback((next: Language) => {
    updateLanguage(next);
    document.documentElement.lang = next === "en" ? "en" : "zh-CN";
    document.title = next === "en" ? "Aperture · Finance Research Workspace" : "Aperture · 金融研究工作台";
    // The server reads this cookie so refreshes render in the chosen language.
    document.cookie = `aperture-locale=${next}; Path=/; Max-Age=31536000; SameSite=Lax`;
    try { localStorage.setItem("aperture-locale", next); } catch { /* Cookie still preserves the preference. */ }
  }, []);
  return <LanguageContext.Provider value={{ language, setLanguage }}>{children}</LanguageContext.Provider>;
}

export const useLanguage = () => useContext(LanguageContext);

export function useT(): Translate {
  const { language } = useLanguage();
  return useCallback(<T,>(text: T): T => {
    if (language !== "en" || typeof text !== "string") return text;
    return translateUI(text, language) as T;
  }, [language]);
}
