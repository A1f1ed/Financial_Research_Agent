import type { NextConfig } from "next";
import { fileURLToPath } from "node:url";

const nextConfig: NextConfig = {
  // Keep the project's own release checks rather than generating agent rules.
  agentRules: false,
  devIndicators: false,
  // Pin the root to this folder. Otherwise a lockfile in a parent folder
  // becomes the workspace root. This value also sets the file tracing root.
  turbopack: { root: fileURLToPath(new URL(".", import.meta.url)) },
  output: "standalone",
  // Keep Inspector/browser diagnostics available without duplicating every
  // gateway event into the development terminal.
  logging: { browserToTerminal: false },
  serverExternalPackages: ["@copilotkit/runtime"],
  env: {
    // NEXT_PUBLIC_* resolves at build time while the Runtime reads the project key
    // per request. Provide CPK_INTELLIGENCE_API_KEY during the host build so the
    // browser gate matches the managed Runtime configuration.
    NEXT_PUBLIC_COPILOTKIT_THREADS_ENABLED: process.env.CPK_INTELLIGENCE_API_KEY
      ? "true"
      : "false",
  },
};

export default nextConfig;
