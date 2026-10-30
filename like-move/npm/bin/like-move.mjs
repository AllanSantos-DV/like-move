#!/usr/bin/env node
// like-move — instala e abre o like-move com um comando, sem administrador (campo `bin` do package.json).
//
//   npx like-move                  # baixa a release, confere o sha256, instala e abre o app
//   npx like-move home-awake       # idem para o Home Awake e roda o 1-diagnosticar (somente leitura)
//   --dir <pasta>                  # instala em outra pasta (padrão: %LOCALAPPDATA%\Programs\like-move)
//   --no-start                     # só instala
import {
  defaultBase, installApp, installHomeAwake, isAppRunning, loadRelease, parseArgs, runHomeAwakeDiagnosis, startApp,
} from "../lib/install.mjs";

const HELP = `Uso: npx like-move [home-awake] [--dir <pasta>] [--no-start]

  (sem argumento)  instala o like-move e abre o app (ícone na bandeja)
  home-awake       instala o Home Awake e roda o passo 1 (diagnóstico, somente leitura)
  --dir <pasta>    instala em outra pasta (padrão: %LOCALAPPDATA%\\Programs\\like-move)
  --no-start       só instala, não abre

O download vem da release do GitHub e só é instalado se o sha256 bater com o que veio no pacote.`;

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) { console.log(HELP); return; }
  if (process.platform !== "win32") throw new Error("o like-move é só para Windows 10 e 11");
  const release = loadRelease();
  const base = opts.dir ?? defaultBase();
  console.log(`like-move ${release.version} (release ${release.tag} de github.com/AllanSantos-DV/like-move)`);

  if (opts.target === "home-awake") {
    const { dir } = await installHomeAwake({ release, base });
    if (opts.start) {
      console.log("Rodando o passo 1 (diagnóstico, somente leitura):");
      runHomeAwakeDiagnosis(dir);
    }
    console.log(`Próximos passos, na pasta ${dir}: 2-cadastrar-rede-de-casa.cmd (em casa, no Wi-Fi de casa) e`
      + " 3-iniciar.cmd. Detalhes em LEIA-ME.txt.");
    return;
  }

  const { exe } = await installApp({ release, base });
  if (!opts.start) { console.log(`Para abrir: "${exe}"`); return; }
  if (isAppRunning()) {
    console.log("O like-move já está aberto (veja o ícone na bandeja); não abri outro.");
    return;
  }
  const pid = await startApp(exe);
  console.log(`like-move aberto (PID ${pid}). O ícone aparece na bandeja do sistema.`);
}

main().catch((err) => {
  console.error(`like-move: ERRO: ${err.message}`);
  process.exit(1);
});
