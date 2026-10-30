// Testes do instalador npm (Windows: usa o tar.exe do sistema). Servidor HTTP local, nada sai para a rede.
//   npm test
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, test } from "node:test";
import {
  APP_ASSET, HOME_AWAKE_ASSET, installApp, installHomeAwake, loadRelease, parseArgs, runHomeAwakeDiagnosis,
} from "../lib/install.mjs";

const TMP = mkdtempSync(join(tmpdir(), "like-move-npm-test-"));
const TAR = join(process.env.SystemRoot || "C:\\Windows", "System32", "tar.exe");
const quiet = () => {};
const sha = (buf) => createHash("sha256").update(buf).digest("hex");

/** Zip com o tar.exe do Windows: `entries` relativos a `dir`. */
function makeZip(name, files, entries) {
  const dir = join(TMP, `src-${name}`);
  for (const [rel, content] of Object.entries(files)) {
    mkdirSync(join(dir, rel, ".."), { recursive: true });
    writeFileSync(join(dir, rel), content);
  }
  const zip = join(TMP, name);
  const r = spawnSync(TAR, ["-a", "-cf", zip, "-C", dir, ...entries], { encoding: "utf8", windowsHide: true });
  assert.equal(r.status, 0, r.stderr);
  return readFileSync(zip);
}

const appZip = makeZip(APP_ASSET, { "like-move/like-move.exe": "MZ fake", "like-move/_internal/base.dat": "x" }, ["like-move"]);
const haZip = makeZip(HOME_AWAKE_ASSET, { "home-awake.ps1": "# v2", "1-diagnosticar.cmd": "@echo off", "LEIA-ME.txt": "leia" },
  ["home-awake.ps1", "1-diagnosticar.cmd", "LEIA-ME.txt"]);
const release = { version: "9.8.7", tag: "v9.8.7", assets: { [APP_ASSET]: sha(appZip), [HOME_AWAKE_ASSET]: sha(haZip) } };

let server, baseUrl;
const hits = [];
const served = { [APP_ASSET]: appZip, [HOME_AWAKE_ASSET]: haZip };
before(async () => {
  server = createServer((req, res) => {
    hits.push(req.url);
    const body = served[req.url.split("/").pop()];
    if (!body) { res.writeHead(404).end(); return; }
    res.writeHead(200, { "content-length": body.length }).end(body);
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  baseUrl = `http://127.0.0.1:${server.address().port}`;
});
after(() => { server.close(); rmSync(TMP, { recursive: true, force: true }); });

const freshBase = (n) => join(TMP, `base-${n}`);
const leftovers = (base) => readdirSync(base).filter((f) => f.startsWith(".staging-"));

test("instala o app em like-move-<versão> com a hash conferida e não deixa temporários", async () => {
  const base = freshBase("app");
  const r = await installApp({ release, base, baseUrl, log: quiet });
  assert.equal(r.installed, true);
  assert.equal(r.exe, join(base, "like-move-9.8.7", "like-move.exe"));
  assert.equal(readFileSync(r.exe, "utf8"), "MZ fake");
  assert.ok(existsSync(join(base, "like-move-9.8.7", "_internal", "base.dat")));
  assert.ok(hits.includes("/v9.8.7/like-move-win64.zip"));
  assert.deepEqual(leftovers(base), []);
});

test("mesma versão já instalada por este comando: não baixa de novo", async () => {
  const base = freshBase("again");
  await installApp({ release, base, baseUrl, log: quiet });
  const before = hits.length;
  const r = await installApp({ release, base, baseUrl, log: quiet });
  assert.equal(r.installed, false);
  assert.equal(hits.length, before);
});

test("hash diferente: recusa e não instala nada", async () => {
  const base = freshBase("bad");
  const wrong = { ...release, assets: { ...release.assets, [APP_ASSET]: "0".repeat(64) } };
  await assert.rejects(installApp({ release: wrong, base, baseUrl, log: quiet }), /sha256 não confere/);
  assert.ok(!existsSync(join(base, "like-move-9.8.7")));
  assert.deepEqual(leftovers(base), []);
});

test("HTTP 404: falha alto", async () => {
  const base = freshBase("404");
  const other = { ...release, assets: { ...release.assets } };
  delete served[APP_ASSET];
  try {
    await assert.rejects(installApp({ release: other, base, baseUrl, log: quiet }), /HTTP 404/);
  } finally {
    served[APP_ASSET] = appZip;
  }
  assert.deepEqual(leftovers(base), []);
});

test("pasta com o mesmo nome que não veio deste comando: erro, nada é sobrescrito", async () => {
  const base = freshBase("foreign");
  mkdirSync(join(base, "like-move-9.8.7"), { recursive: true });
  writeFileSync(join(base, "like-move-9.8.7", "like-move.exe"), "outro");
  await assert.rejects(installApp({ release, base, baseUrl, log: quiet }), /não foi instalada por este comando/);
  assert.equal(readFileSync(join(base, "like-move-9.8.7", "like-move.exe"), "utf8"), "outro");
});

test("Home Awake: troca os scripts e mantém o cadastro.txt", async () => {
  const base = freshBase("ha");
  mkdirSync(join(base, "home-awake"), { recursive: true });
  writeFileSync(join(base, "home-awake", "home-awake.ps1"), "# v1");
  writeFileSync(join(base, "home-awake", "cadastro.txt"), "minha rede");
  const { dir } = await installHomeAwake({ release, base, baseUrl, log: quiet });
  assert.equal(readFileSync(join(dir, "home-awake.ps1"), "utf8"), "# v2");
  assert.equal(readFileSync(join(dir, "cadastro.txt"), "utf8"), "minha rede");
  assert.ok(existsSync(join(dir, "1-diagnosticar.cmd")));
  assert.deepEqual(leftovers(base), []);
});

test("diagnóstico do Home Awake roda mesmo com NoDefaultCurrentDirectoryInExePath definido", () => {
  const dir = join(TMP, "diag");
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "1-diagnosticar.cmd"), "@echo off\r\necho ok> rodou.txt\r\n");
  const before = process.env.NoDefaultCurrentDirectoryInExePath;
  process.env.NoDefaultCurrentDirectoryInExePath = "1";
  try {
    runHomeAwakeDiagnosis(dir);
  } finally {
    if (before === undefined) delete process.env.NoDefaultCurrentDirectoryInExePath;
    else process.env.NoDefaultCurrentDirectoryInExePath = before;
  }
  assert.ok(existsSync(join(dir, "rodou.txt")));
});

test("release.json: ausente ou com hash inválida falha alto", () => {
  assert.throws(() => loadRelease(join(TMP, "nao-existe.json")), /release.json ausente/);
  const p = join(TMP, "rel.json");
  writeFileSync(p, JSON.stringify({ ...release, assets: { [APP_ASSET]: "abc" } }));
  assert.throws(() => loadRelease(p), /sem sha256 válido/);
  writeFileSync(p, JSON.stringify({ ...release, tag: "v1.0.0" }));
  assert.throws(() => loadRelease(p), /inválido/);
  writeFileSync(p, JSON.stringify(release));
  assert.deepEqual(loadRelease(p), release);
});

test("argumentos", () => {
  assert.deepEqual(parseArgs([]), { target: "app", dir: null, start: true, help: false });
  assert.deepEqual(parseArgs(["home-awake", "--dir", "C:\\x", "--no-start"]),
    { target: "home-awake", dir: "C:\\x", start: false, help: false });
  assert.throws(() => parseArgs(["--dir"]), /precisa de uma pasta/);
  assert.throws(() => parseArgs(["--force"]), /desconhecido/);
});

test("package.json na versão do app (like-move/VERSION)", () => {
  const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  const app = readFileSync(new URL("../../VERSION", import.meta.url), "utf8").trim();
  assert.equal(pkg.version, app);
  assert.deepEqual(pkg.files.sort(), ["README.md", "bin", "lib", "release.json"]);
});
