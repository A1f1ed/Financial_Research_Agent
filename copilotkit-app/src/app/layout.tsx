"use client";

import "./globals.css";
import "@copilotkit/react-core/v2/styles.css";
import "./research.css";

import { CopilotKit } from "@copilotkit/react-core/v2";
import { ThemeProvider } from "@/hooks/use-theme";
// A2UI catalog: definitions + renderers in ./declarative-generative-ui/
import { demonstrationCatalog } from "./declarative-generative-ui/renderers";

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <title>Aperture · 金融研究工作台</title>
        <meta name="description" content="保留原生 CopilotKit 对话与运行追踪的多分析师金融研究工作台。" />
        <link
          rel="icon"
          type="image/svg+xml"
          href="/copilotkit-logo-mark.svg"
        />
        {/*
          Set the theme class BEFORE first paint to avoid a white→dark flash.
          ThemeProvider applies the theme in a useEffect (post-hydration), so
          without this the page paints unthemed (light) first, then flips. This
          blocking inline script matches ThemeProvider's "system" default so
          there's no flash and no class mismatch when the provider re-applies.
        */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "(function(){try{document.documentElement.classList.add(localStorage.getItem('aperture-theme')==='light'?'light':'dark');}catch(e){document.documentElement.classList.add('dark');}})();",
          }}
        />
      </head>
      {/*
        suppressHydrationWarning: browser extensions (e.g. Grammarly) inject
        attributes like data-gr-ext-installed onto <body> before React hydrates,
        which would otherwise surface as a hydration mismatch on first load.
        This only relaxes the check for <body>'s own attributes (one level deep);
        everything rendered inside <body> is still fully hydration-checked.
      */}
      <body className={`antialiased`} suppressHydrationWarning>
        <ThemeProvider>
          <CopilotKit
            runtimeUrl="/api/copilotkit"
            a2ui={{ catalog: demonstrationCatalog }}
            openGenerativeUI={{}}
            useSingleEndpoint={false}
          >
            {children}
          </CopilotKit>
        </ThemeProvider>
      </body>
    </html>
  );
}
