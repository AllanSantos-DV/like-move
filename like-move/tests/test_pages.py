"""Pages pela branch gh-pages: publicação sem artefato do Actions, guarda de conteúdo e conferência da página no ar.

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import http.server
import os
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pages  # noqa: E402

WORKFLOW = os.path.join(pages.REPO, ".github", "workflows", "pages.yml")
INDEX = "<!DOCTYPE html>\n<html>\n<head>\n<title>t</title>\n</head>\n<body>like-move</body>\n</html>\n"


def run_git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def make_repo(root, files):
    """Repositório com like-move/VERSION e os ``files`` (caminho relativo → texto) versionados."""
    files = {"like-move/VERSION": "9.8.7\n", **files}
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    run_git("init", "-q", cwd=root)
    run_git("add", "-A", cwd=root)
    return root


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        with open(WORKFLOW, encoding="utf-8") as f:
            self.text = f.read()

    def test_sem_artefato_do_actions(self):
        for word in ("deploy-pages", "upload-pages-artifact", "id-token"):
            self.assertNotIn(word, self.text)

    def test_push_com_a_chave_de_deploy(self):
        self.assertIn("secrets.PAGES_DEPLOY_KEY", self.text)
        self.assertNotIn("secrets.GITHUB_TOKEN", self.text)
        self.assertNotIn("github.token", self.text)

    def test_confere_a_pagina_no_ar(self):
        self.assertIn("pages.py publish", self.text)
        self.assertIn("pages.py verify", self.text)

    def test_so_publica_da_main(self):
        self.assertIn("branches: [main]", self.text)
        self.assertIn("github.ref == 'refs/heads/main'", self.text)


class CheckSiteTest(unittest.TestCase):
    def check(self, files):
        with tempfile.TemporaryDirectory() as root:
            make_repo(root, files)
            pages.check_site(root, pages.site_files(root))

    def test_site_publico_passa(self):
        self.check({"like-move/site/index.html": INDEX, "like-move/site/a.png": "x"})

    def test_sem_index_versionado_recusa(self):
        with self.assertRaisesRegex(pages.PagesError, "index.html"):
            self.check({"like-move/site/a.png": "x"})

    def test_tipo_fora_de_pagina_e_midia_recusa(self):
        with self.assertRaisesRegex(pages.PagesError, "voz.json"):
            self.check({"like-move/site/index.html": INDEX, "like-move/site/x.voz.json": "{}"})

    def test_quadro_narrado_recusa(self):
        with self.assertRaisesRegex(pages.PagesError, "vxp-speed"):
            self.check({"like-move/site/index.html": INDEX.replace("like-move", '<div class="vxp-speed">')})

    def test_arquivo_so_no_disco_nao_entra(self):
        with tempfile.TemporaryDirectory() as root:
            make_repo(root, {"like-move/site/index.html": INDEX})
            open(os.path.join(root, "like-move", "site", "fora.voz.json"), "w").close()
            self.assertEqual(pages.site_files(root), ["like-move/site/index.html"])


class StampTest(unittest.TestCase):
    def test_carimba_logo_depois_do_head(self):
        out = pages.stamp_html(INDEX, "9.8.7 abc1234")
        self.assertIn('<head>\n<meta name="like-move-version" content="9.8.7 abc1234" />', out)

    def test_sem_head_recusa(self):
        with self.assertRaises(pages.PagesError):
            pages.stamp_html("<html></html>", "1")


class PublishTest(unittest.TestCase):
    def test_publica_commit_orfao_so_com_o_site_carimbado(self):
        with tempfile.TemporaryDirectory() as root:
            repo = make_repo(os.path.join(root, "repo"), {
                "like-move/site/index.html": INDEX, "like-move/site/assets/a.png": "x", "like-move/main.pyw": "app",
            })
            bare = os.path.join(root, "remote.git")
            run_git("init", "-q", "--bare", bare, cwd=root)
            stamp, _ = pages.publish(repo, bare, "", "abcdef0123", "Página")
            self.assertEqual(stamp, "9.8.7 abcdef0")
            listed = subprocess.run(["git", "ls-tree", "-r", "--name-only", "gh-pages"], cwd=bare,
                                    check=True, capture_output=True, text=True).stdout.split()
            self.assertEqual(sorted(listed), [".nojekyll", "assets/a.png", "index.html"])
            count = subprocess.run(["git", "rev-list", "--count", "gh-pages"], cwd=bare,
                                   check=True, capture_output=True, text=True).stdout.strip()
            self.assertEqual(count, "1")
            index = subprocess.run(["git", "show", "gh-pages:index.html"], cwd=bare,
                                   check=True, capture_output=True, text=True, encoding="utf-8").stdout
            self.assertEqual(index, pages.expected_index(repo, stamp))

    def test_remoto_ssh_sem_chave_recusa(self):
        with tempfile.TemporaryDirectory() as root:
            make_repo(root, {"like-move/site/index.html": INDEX})
            with self.assertRaisesRegex(pages.PagesError, "PAGES_DEPLOY_KEY"):
                pages.publish(root, "git@github.com:o/r.git", "", "abcdef0", "m")


class VerifyTest(unittest.TestCase):
    def serve(self, body):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}/"

    def test_pagina_publicada_no_ar_passa(self):
        expected = pages.stamp_html(INDEX, "9.8.7 abc1234")
        pages.verify(self.serve(expected.replace("\n", "\r\n")), expected, attempts=1, interval=0)

    def test_pagina_com_outro_carimbo_falha(self):
        live = pages.stamp_html(INDEX, "9.8.6 0000000")
        with self.assertRaisesRegex(pages.PagesError, "não mostra a página publicada"):
            pages.verify(self.serve(live), pages.stamp_html(INDEX, "9.8.7 abc1234"), attempts=1, interval=0)


if __name__ == "__main__":
    unittest.main()
