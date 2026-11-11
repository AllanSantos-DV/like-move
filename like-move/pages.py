#!/usr/bin/env python3
"""Publica like-move/site na branch gh-pages e confere a página no ar, sem artefato do Actions.

  publish: monta um commit órfão só com os arquivos versionados de like-move/site (mais .nojekyll), carimba o
           index.html com <meta name="like-move-version" content="<VERSION> <commit>"> e faz push forçado na gh-pages.
           Remoto SSH exige a chave privada de deploy em PAGES_DEPLOY_KEY: push com GITHUB_TOKEN não dispara o Pages.
  verify:  lê a URL pública até o index.html no ar ser o publicado, com o mesmo carimbo; senão termina com código 1.

Reverter para o Actions: PUT /repos/{owner}/{repo}/pages com build_type=workflow e git revert da migração.
Qualquer configuração inválida termina com código 1 e a causa na saída de erro.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT)
SITE = "like-move/site"
BRANCH = "gh-pages"
KEY_ENV = "PAGES_DEPLOY_KEY"
KNOWN_HOSTS = os.path.join(ROOT, "github_known_hosts")
DEFAULT_REMOTE = "git@github.com:AllanSantos-DV/like-move.git"
DEFAULT_URL = "https://allansantos-dv.github.io/like-move/"
STAMP_NAME = "like-move-version"
ALLOWED = {".html", ".png", ".jpg", ".mp4", ".vtt"}
# Marcas do quadro narrado do VXK: botão Explicar, controle de velocidade, estado de narração, voz do navegador.
NARRATED_BOARD_MARKERS = ("Explicar", "vxp-speed", "bd-narrating", "data-vxp", "speech" + "Synthesis", "like-move-tour")


class PagesError(Exception):
    pass


def git(*args, cwd, env=None):
    """Roda git em ``cwd`` e devolve a saída; PagesError com a mensagem do git se falhar."""
    result = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise PagesError(f"git {args[0]} falhou ({result.returncode}): {(result.stderr or result.stdout).strip()}")
    return result.stdout


def site_files(repo=REPO):
    """Arquivos versionados do site, relativos ao repositório: o que está só no disco nunca vai ao ar."""
    return [line for line in git("ls-files", SITE, cwd=repo).splitlines() if line]


def public_findings(repo, files):
    """Motivos para o site não ir ao ar: tipo fora de página/mídia, pasta ou quadro narrado internos."""
    found = []
    for path in files:
        if os.path.splitext(path)[1].lower() not in ALLOWED:
            found.append(f"{path}: tipo de arquivo fora de página/mídia")
        if "apresentacao/" in path:
            found.append(f"{path}: pasta da apresentação interna")
        if path.endswith(".html"):
            with open(os.path.join(repo, path), encoding="utf-8") as f:
                html = f.read()
            found += [f"{path}: {m}" for m in NARRATED_BOARD_MARKERS if m in html]
    return found


def check_site(repo, files):
    """PagesError se o site não tem index.html versionado, tem link simbólico ou conteúdo que não pode ser público."""
    if f"{SITE}/index.html" not in files:
        raise PagesError(f"{SITE}/index.html não está versionado: nada a publicar")
    links = [p for p in files if os.path.islink(os.path.join(repo, p))]
    if links:
        raise PagesError(f"links simbólicos no site (o Pages por branch não os publica): {', '.join(links)}")
    found = public_findings(repo, files)
    if found:
        raise PagesError("o site tem conteúdo que não pode ser público: " + "; ".join(found))


def stamp_html(html, stamp):
    """Devolve ``html`` com a meta like-move-version logo após <head>."""
    if "<head>" not in html:
        raise PagesError("index.html sem <head>: não há onde carimbar a versão")
    return html.replace("<head>", f'<head>\n<meta name="{STAMP_NAME}" content="{stamp}" />', 1)


def product_stamp(repo, commit):
    """Carimbo "<VERSION> <commit curto>" da publicação."""
    with open(os.path.join(repo, "like-move", "VERSION"), encoding="utf-8") as f:
        version = f.read().strip()
    if not version:
        raise PagesError("like-move/VERSION vazio")
    return f"{version} {commit[:7]}"


def stage_tree(repo, files, destination, stamp):
    """Copia ``files`` (sem o prefixo do site) para ``destination``, carimba o index.html e cria .nojekyll."""
    for path in files:
        target = os.path.join(destination, os.path.relpath(path, SITE))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.join(repo, path), target)
    index = os.path.join(destination, "index.html")
    with open(index, encoding="utf-8") as f:
        html = f.read()
    with open(index, "w", encoding="utf-8", newline="") as f:
        f.write(stamp_html(html, stamp))
    open(os.path.join(destination, ".nojekyll"), "w").close()


def write_key(path, key):
    """Grava a chave privada em ``path`` só para o dono do arquivo."""
    # LF puro: o ssh recusa chave com CRLF ("error in libcrypto").
    with open(path, "wb") as f:
        f.write(key.replace("\r", "").strip().encode("utf-8") + b"\n")
    os.chmod(path, 0o600)


def ssh_command(key_file, known_hosts=KNOWN_HOSTS):
    """ssh do push: só a chave de deploy, e só o host do GitHub com as chaves fixadas (sem aprender host na hora)."""
    return (f'ssh -i "{key_file}" -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes '
            f'-o UserKnownHostsFile="{known_hosts}"')


def publish(repo, remote, key, commit, message):
    """Publica o site na gh-pages de ``remote`` com push forçado; devolve (carimbo, sha do commit publicado)."""
    files = site_files(repo)
    check_site(repo, files)
    stamp = product_stamp(repo, commit)
    over_ssh = remote.startswith(("git@", "ssh://"))
    if over_ssh and "PRIVATE KEY" not in key:
        raise PagesError(f"{KEY_ENV} ausente ou não é uma chave privada: remoto SSH exige a chave de deploy")
    with tempfile.TemporaryDirectory() as temp:
        env = dict(os.environ)
        if over_ssh:
            key_file = os.path.join(temp, "deploy_key")
            write_key(key_file, key)
            env["GIT_SSH_COMMAND"] = ssh_command(key_file)
        tree = os.path.join(temp, "tree")
        os.makedirs(tree)
        stage_tree(repo, files, tree, stamp)
        git("init", "-q", "-b", BRANCH, cwd=tree)
        git("add", "-A", cwd=tree)
        git("-c", "user.name=github-actions[bot]", "-c",
            "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "commit", "-q", "-m", f"{message} ({stamp})", cwd=tree)
        git("push", "--force", remote, f"HEAD:refs/heads/{BRANCH}", cwd=tree, env=env)
        return stamp, git("rev-parse", "HEAD", cwd=tree).strip()


def expected_index(repo, stamp):
    """O index.html que deve estar no ar para ``stamp``."""
    with open(os.path.join(repo, SITE, "index.html"), encoding="utf-8") as f:
        return stamp_html(f.read(), stamp)


def verify(url, expected, attempts, interval):
    """Lê ``url`` até o corpo ser ``expected`` (fim de linha normalizado); PagesError se não for."""
    want = expected.replace("\r\n", "\n")
    last = "sem resposta"
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(f"{url}?v={int(time.time())}", timeout=30) as response:
                body = response.read().decode("utf-8", errors="replace").replace("\r\n", "\n")
            if body == want:
                return
            last = "a página responde, mas não é o index.html publicado com este carimbo"
        except (urllib.error.URLError, OSError) as error:
            last = str(error)
        if attempt + 1 < attempts:
            time.sleep(interval)
    raise PagesError(f"{url} não mostra a página publicada depois de {attempts} tentativas ({last})")


def main(argv=None):
    """CLI: publish ou verify; código 1 com a causa em qualquer falha."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("publish", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--commit", default=None, help="commit do site (padrão: HEAD)")
    sub.choices["publish"].add_argument("--remote", default=DEFAULT_REMOTE)
    sub.choices["publish"].add_argument("--message", default="Página do like-move")
    sub.choices["verify"].add_argument("--url", default=DEFAULT_URL)
    sub.choices["verify"].add_argument("--attempts", type=int, default=20)
    sub.choices["verify"].add_argument("--interval", type=float, default=15)
    args = parser.parse_args(argv)
    try:
        commit = args.commit or git("rev-parse", "HEAD", cwd=REPO).strip()
        if args.command == "publish":
            stamp, sha = publish(REPO, args.remote, os.environ.get(KEY_ENV, ""), commit, args.message)
            print(f"{BRANCH} publicada em {sha} ({stamp}).")
        else:
            stamp = product_stamp(REPO, commit)
            verify(args.url, expected_index(REPO, stamp), args.attempts, args.interval)
            print(f"A página no ar é a publicada ({stamp}).")
    except PagesError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
