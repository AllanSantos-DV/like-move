#!/usr/bin/env node
// prepublishOnly: só publica com release.json válido e com package.json, release.json e like-move/VERSION
// na mesma versão (o pacote 1.3.4 instala a release v1.3.4).
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadRelease } from "../lib/install.mjs";

const PKG_DIR = dirname(dirname(fileURLToPath(import.meta.url)));
const release = loadRelease(join(PKG_DIR, "release.json"));
const pkg = JSON.parse(readFileSync(join(PKG_DIR, "package.json"), "utf8")).version;
const app = readFileSync(join(PKG_DIR, "..", "VERSION"), "utf8").trim();
if (pkg !== app || release.version !== app) {
  console.error(`versões divergentes: package.json=${pkg} release.json=${release.version} VERSION=${app}`);
  process.exit(1);
}
console.log(`ok: like-move ${app}, release ${release.tag}`);
