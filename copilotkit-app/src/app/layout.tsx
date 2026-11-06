import "./globals.css";
import "@copilotkit/react-core/v2/styles.css";
import "./research.css";

import { cookies } from "next/headers";
import { AppProviders } from "./providers";

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const language = (await cookies()).get("aperture-locale")?.value === "zh" ? "zh" : "en";
  return (
    <html lang={language === "en" ? "en" : "zh-CN"} suppressHydrationWarning>
      <head>
        <title>{language === "en" ? "Aperture · Finance Research Workspace" : "Aperture · 金融研究工作台"}</title>
        <meta name="description" content={language === "en" ? "A multi-analyst finance research workspace with native CopilotKit chat and run tracing." : "保留原生 CopilotKit 对话与运行追踪的多分析师金融研究工作台。"} />
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
        <AppProviders language={language}>{children}</AppProviders>
      </body>
    </html>
  );
}
