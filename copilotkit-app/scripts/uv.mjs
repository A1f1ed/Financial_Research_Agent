import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const root = new URL("../", import.meta.url);
const localUv = fileURLToPath(new URL(process.platform === "win32" ? ".tools/bin/uv.exe" : ".tools/bin/uv", root));
const result = spawnSync(existsSync(localUv) ? localUv : "uv", process.argv.slice(2), {
  cwd: fileURLToPath(new URL("agent/", root)),
  stdio: "inherit",
  env: process.env,
});
if (result.error) {
  console.error("Python setup needs uv: https://docs.astral.sh/uv/getting-started/installation/");
}
process.exit(result.status ?? 1);
