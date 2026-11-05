import { cp, mkdir, access } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import { resolve } from "node:path";
import nextEnv from "@next/env";

const root = fileURLToPath(new URL("../", import.meta.url));
const output = resolve(root, ".next/standalone");
const server = resolve(output, "server.js");
// Load server credentials from the project directory without copying .env into
// the generated deployment files. Existing process variables keep precedence.
nextEnv.loadEnvConfig(root, false);

try {
  await access(server);
} catch {
  console.error("Production build missing. Run npm run build first.");
  process.exit(1);
}

// Next's standalone output omits public/static assets. Keep the local production
// command complete, including after a fresh build, without a separate copy step.
await mkdir(resolve(output, ".next"), { recursive: true });
await cp(resolve(root, "public"), resolve(output, "public"), { recursive: true });
await cp(resolve(root, ".next/static"), resolve(output, ".next/static"), { recursive: true });

process.env.HOSTNAME = process.env.APERTURE_HOST || "127.0.0.1";
process.env.PORT ||= "3000";
await import(pathToFileURL(server).href);
