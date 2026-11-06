"use client";

import { CopilotKit } from "@copilotkit/react-core/v2";
import { ThemeProvider } from "@/hooks/use-theme";
import { LanguageProvider, type Language } from "@/hooks/use-language";
import { demonstrationCatalog } from "./declarative-generative-ui/renderers";

export function AppProviders({ language, children }: { language: Language; children: React.ReactNode }) {
  return <LanguageProvider initialLanguage={language}><ThemeProvider>
    <CopilotKit runtimeUrl="/api/copilotkit" a2ui={{ catalog: demonstrationCatalog }} openGenerativeUI={{}} useSingleEndpoint={false}>
      {children}
    </CopilotKit>
  </ThemeProvider></LanguageProvider>;
}
