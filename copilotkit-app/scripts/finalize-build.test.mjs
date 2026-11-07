import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, realpath, writeFile, lstat, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import test from "node:test";
import { finalizeStandalone } from "./finalize-build.mjs";

test("standalone cleanup preserves source configuration and executable output", async () => {
  const root = await mkdtemp(join(tmpdir(), "aperture-build-test-"));
  try {
    const output = join(root, ".next", "standalone"); await mkdir(output, { recursive: true });
    await writeFile(join(root, ".env"), "SYNTHETIC_CANARY=source-kept\n");
    await writeFile(join(output, ".env"), "SYNTHETIC_CANARY=copied\n");
    await writeFile(join(output, ".env.production"), "SYNTHETIC_CANARY=copied-production\n");
    await writeFile(join(output, ".env.local"), "SYNTHETIC_CANARY=additional-copy\n");
    await writeFile(join(output, "server.js"), "// retained generated server\n");
    await finalizeStandalone(root); await finalizeStandalone(root);
    for (const name of [".env", ".env.production", ".env.local"]) await assert.rejects(lstat(join(output, name)), { code: "ENOENT" });
    assert.match(await readFile(join(root, ".env"), "utf8"), /source-kept/);
    assert.match(await readFile(join(output, "server.js"), "utf8"), /retained/);
  } finally {
    assert.equal(dirname(await realpath(root)), await realpath(tmpdir()));
    assert.match(basename(root), /^aperture-build-test-/);
    await rm(root, { recursive: true, force: true });
  }
});
