#!/usr/bin/env node
// Gera release.json com o sha256 dos assets da release v<VERSION> já publicada (não rascunho).
// Cada asset é baixado e a hash calculada aqui tem de bater com o digest que o GitHub publica na release.
//
//   node scripts/release-hashes.mjs            # usa like-move/VERSION
//   GITHUB_TOKEN=... node scripts/release-hashes.mjs   # na CI, sem limite de taxa da API anônima
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { APP_ASSET, HOME_AWAKE_ASSET, REPO, download } from "../lib/install.mjs";

const PKG_DIR = dirname(dirname(fileURLToPath(import.meta.url)));
const version = readFileSync(join(PKG_DIR, "..", "VERSION"), "utf8").trim();
const tag = `v${version}`;
const headers = { "user-agent": "like-move-npm", accept: "application/vnd.github+json" };
if (process.env.GITHUB_TOKEN) headers.authorization = `Bearer ${process.env.GITHUB_TOKEN}`;

const res = await fetch(`https://api.github.com/repos/${REPO}/releases/tags/${tag}`, { headers });
if (!res.ok) throw new Error(`release ${tag} não encontrada: HTTP ${res.status}`);
const rel = await res.json();
if (rel.draft) throw new Error(`release ${tag} ainda é rascunho`);

const tmp = mkdtempSync(join(tmpdir(), "like-move-hashes-"));
const assets = {};
try {
  for (const name of [APP_ASSET, HOME_AWAKE_ASSET]) {
    const a = rel.assets.find((x) => x.name === name);
    if (!a) throw new Error(`release ${tag} sem o asset ${name}`);
    const published = /^sha256:([0-9a-f]{64})$/.exec(a.digest ?? "")?.[1];
    if (!published) throw new Error(`release ${tag}: ${name} sem digest sha256 publicado pelo GitHub`);
    const got = await download(a.browser_download_url, join(tmp, name));
    if (got !== published) throw new Error(`${name}: baixado ${got}, GitHub publica ${published}`);
    assets[name] = got;
    console.log(`${name} ${got}`);
  }
} finally {
  rmSync(tmp, { recursive: true, force: true });
}
writeFileSync(join(PKG_DIR, "release.json"), JSON.stringify({ version, tag, assets }, null, 2) + "\n");
console.log(`release.json gravado para ${tag}`);
