// like-move/npm/lib/install.mjs — baixa um asset da release do GitHub, confere o sha256 embarcado no pacote
// (release.json, gerado de uma release já publicada) e instala sem administrador.
//
// Sem dependências: fetch do Node, hash do node:crypto e o tar.exe do próprio Windows (bsdtar, que lê zip).
// Nada é instalado se a hash não bater: o download fica numa pasta temporária que some no fim.
import { createHash, randomBytes } from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import {
  copyFileSync, createWriteStream, existsSync, mkdirSync, readFileSync, readdirSync, renameSync, rmSync, statSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { Transform } from "node:stream";
import { pipeline } from "node:stream/promises";
import { fileURLToPath } from "node:url";

export const REPO = "AllanSantos-DV/like-move";
export const DOWNLOAD_BASE = `https://github.com/${REPO}/releases/download`;
export const APP_ASSET = "like-move-win64.zip";
export const HOME_AWAKE_ASSET = "home-awake.zip";
export const EXE_NAME = "like-move.exe";
const PKG_DIR = dirname(dirname(fileURLToPath(import.meta.url)));

/** release.json do pacote: { version, tag, assets: { <nome>: <sha256 hex> } }. Falha alto se faltar ou vier torto. */
export function loadRelease(path = join(PKG_DIR, "release.json")) {
  if (!existsSync(path)) throw new Error(`release.json ausente em ${path}: pacote montado sem as hashes da release`);
  const r = JSON.parse(readFileSync(path, "utf8"));
  if (!/^\d+\.\d+\.\d+$/.test(r.version ?? "") || r.tag !== `v${r.version}`) {
    throw new Error(`release.json inválido: version=${r.version} tag=${r.tag}`);
  }
  for (const name of [APP_ASSET, HOME_AWAKE_ASSET]) {
    if (!/^[0-9a-f]{64}$/.test(r.assets?.[name] ?? "")) throw new Error(`release.json sem sha256 válido para ${name}`);
  }
  return r;
}

/** Pasta padrão: %LOCALAPPDATA%\Programs\like-move (por usuário, sem administrador). */
export function defaultBase(env = process.env) {
  if (!env.LOCALAPPDATA) throw new Error("LOCALAPPDATA não definido: use --dir <pasta>");
  return join(env.LOCALAPPDATA, "Programs", "like-move");
}

/** Baixa `url` para `dest` e devolve o sha256 (hex) do que foi gravado. */
export async function download(url, dest, fetchImpl = fetch) {
  const res = await fetchImpl(url, { redirect: "follow", headers: { "user-agent": "like-move-npm" } });
  if (!res.ok || !res.body) throw new Error(`download falhou: HTTP ${res.status} em ${url}`);
  const hash = createHash("sha256");
  const tap = new Transform({ transform(chunk, _enc, cb) { hash.update(chunk); cb(null, chunk); } });
  await pipeline(res.body, tap, createWriteStream(dest));
  return hash.digest("hex");
}

/** Extrai o zip com o tar.exe do Windows (o tar do Git/MSYS não lê zip). bsdtar recusa caminhos com "..". */
export function extractZip(zip, destDir, env = process.env) {
  const tar = join(env.SystemRoot || "C:\\Windows", "System32", "tar.exe");
  const r = spawnSync(tar, ["-xf", zip, "-C", destDir], { windowsHide: true, encoding: "utf8" });
  if (r.error) throw new Error(`não consegui rodar ${tar}: ${r.error.message}`);
  if (r.status !== 0) throw new Error(`tar.exe falhou (${r.status}) ao extrair ${zip}: ${r.stderr.trim()}`);
}

/** Baixa e confere um asset numa pasta temporária dentro de `base`; devolve a pasta com o zip extraído. */
async function fetchVerified({ release, asset, base, baseUrl, log, fetchImpl }) {
  const expected = release.assets[asset];
  const url = `${baseUrl}/${release.tag}/${asset}`;
  mkdirSync(base, { recursive: true });
  const staging = join(base, `.staging-${randomBytes(4).toString("hex")}`);
  mkdirSync(staging);
  try {
    log(`Baixando ${url}`);
    const zip = join(staging, asset);
    const got = await download(url, zip, fetchImpl);
    if (got !== expected) {
      throw new Error(`sha256 não confere para ${asset}: esperado ${expected}, recebido ${got}. Nada foi instalado.`);
    }
    log(`sha256 conferido: ${got}`);
    const out = join(staging, "x");
    mkdirSync(out);
    extractZip(zip, out);
    return { staging, out };
  } catch (err) {
    rmSync(staging, { recursive: true, force: true });
    throw err;
  }
}

/** Raiz do conteúdo: o zip do app traz uma pasta (like-move/); aceita também o conteúdo solto, como o updater. */
function contentRoot(dir) {
  const entries = readdirSync(dir);
  const only = entries.length === 1 ? join(dir, entries[0]) : null;
  return only && statSync(only).isDirectory() ? only : dir;
}

/**
 * Instala o app em <base>\like-move-<versão> (o mesmo nome de pasta que o auto-update do app usa).
 * Já instalado por este comando com a mesma hash: não baixa de novo. Pasta com o mesmo nome vinda de outro lugar: erro.
 */
export async function installApp({ release, base, baseUrl = DOWNLOAD_BASE, log = console.log, fetchImpl = fetch }) {
  const target = join(base, `like-move-${release.version}`);
  const exe = join(target, EXE_NAME);
  const marker = join(base, `like-move-${release.version}.npm.json`);
  const expected = release.assets[APP_ASSET];
  if (existsSync(target)) {
    const recorded = existsSync(marker) ? JSON.parse(readFileSync(marker, "utf8")).sha256 : null;
    if (recorded === expected && existsSync(exe)) {
      log(`like-move ${release.version} já instalado em ${target}`);
      return { exe, installed: false };
    }
    throw new Error(`${target} já existe e não foi instalada por este comando (ou está incompleta). `
      + "Apague a pasta ou use --dir <outra pasta>.");
  }
  const { staging, out } = await fetchVerified({ release, asset: APP_ASSET, base, baseUrl, log, fetchImpl });
  try {
    const root = contentRoot(out);
    if (!existsSync(join(root, EXE_NAME))) throw new Error(`${APP_ASSET} sem ${EXE_NAME}`);
    renameSync(root, target);
    writeFileSync(marker, JSON.stringify({ version: release.version, asset: APP_ASSET, sha256: expected }, null, 2));
  } finally {
    rmSync(staging, { recursive: true, force: true });
  }
  log(`Instalado em ${target}`);
  return { exe, installed: true };
}

/** Instala o Home Awake em <base>\home-awake: troca só os scripts e o LEIA-ME, o cadastro.txt de quem já usa fica. */
export async function installHomeAwake({ release, base, baseUrl = DOWNLOAD_BASE, log = console.log, fetchImpl = fetch }) {
  const target = join(base, "home-awake");
  const { staging, out } = await fetchVerified({ release, asset: HOME_AWAKE_ASSET, base, baseUrl, log, fetchImpl });
  try {
    const root = contentRoot(out);
    const files = readdirSync(root);
    if (!files.includes("home-awake.ps1")) throw new Error(`${HOME_AWAKE_ASSET} sem home-awake.ps1`);
    mkdirSync(target, { recursive: true });
    for (const f of files) copyFileSync(join(root, f), join(target, f));
  } finally {
    rmSync(staging, { recursive: true, force: true });
  }
  log(`Home Awake ${release.version} em ${target}`);
  return { dir: target };
}

/** True se algum like-move.exe já está aberto nesta sessão do usuário. */
export function isAppRunning() {
  const r = spawnSync("tasklist", ["/FI", `IMAGENAME eq ${EXE_NAME}`, "/FO", "CSV", "/NH"], { windowsHide: true, encoding: "utf8" });
  if (r.status !== 0) throw new Error(`tasklist falhou (${r.status}): ${r.stderr}`);
  return r.stdout.toLowerCase().includes(`"${EXE_NAME}"`);
}

/** Abre o app desacoplado do terminal (é um app de bandeja com janela: visível de propósito). Devolve o PID. */
export function startApp(exe) {
  return new Promise((resolve, reject) => {
    const child = spawn(exe, [], { cwd: dirname(exe), detached: true, stdio: "ignore" });
    child.once("error", reject);
    child.once("spawn", () => { child.unref(); resolve(child.pid); });
  });
}

/** Roda o passo 1 do Home Awake (somente leitura) neste mesmo terminal. */
export function runHomeAwakeDiagnosis(dir) {
  // ".\" explícito: com NoDefaultCurrentDirectoryInExePath definido o cmd não procura o nome solto na pasta atual.
  const r = spawnSync("cmd.exe", ["/d", "/c", ".\\1-diagnosticar.cmd"], { cwd: dir, stdio: "inherit", windowsHide: true });
  if (r.error) throw new Error(`não consegui rodar 1-diagnosticar.cmd: ${r.error.message}`);
  if (r.status !== 0) throw new Error(`1-diagnosticar.cmd terminou com código ${r.status}`);
}

/** Argumentos: [home-awake] [--dir <pasta>] [--no-start] [--help]. Desconhecido = erro. */
export function parseArgs(argv) {
  const opts = { target: "app", dir: null, start: true, help: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "home-awake" && opts.target === "app") opts.target = "home-awake";
    else if (a === "--dir") {
      if (!argv[i + 1] || argv[i + 1].startsWith("--")) throw new Error("--dir precisa de uma pasta");
      opts.dir = argv[++i];
    } else if (a === "--no-start") opts.start = false;
    else if (a === "--help" || a === "-h") opts.help = true;
    else throw new Error(`argumento desconhecido: ${a}`);
  }
  return opts;
}
