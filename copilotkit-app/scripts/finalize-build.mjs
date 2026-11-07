// Next's standalone writer explicitly copies .env and .env.production after
// dependency tracing. Runtime credentials belong to deployment configuration,
// not a distributable build. Never touch the project's actual env files.
import { lstat, readdir, realpath, unlink } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

export async function finalizeStandalone(appDirectory) {
  const root = await realpath(appDirectory);
  const expected = resolve(root, ".next/standalone");
  const actual = await realpath(expected);
  const canonical = value => process.platform === "win32" ? value.toLowerCase() : value;
  if (canonical(actual) !== canonical(expected)) throw new Error("Standalone output resolves outside the build directory");
  for (const name of (await readdir(expected)).filter(value => value === ".env" || value.startsWith(".env."))) {
    const filename = resolve(expected, name);
    try {
      const stat = await lstat(filename);
      if (!stat.isFile() && !stat.isSymbolicLink()) throw new Error("Unexpected generated environment entry type");
      await unlink(filename);
    } catch (error) { if (error.code !== "ENOENT") throw error; }
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await finalizeStandalone(fileURLToPath(new URL("../", import.meta.url)));
  console.log("Standalone build finalized without copied environment files.");
}
