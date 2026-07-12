"""Gera PNGs reais das telas do like-move — SEM abrir nenhuma janela.

As imagens do app (ícone do tray, splash e janela "Sobre") são desenhadas
por código com Pillow. Este script chama exatamente essas mesmas funções de
desenho e salva o resultado como PNG, para uso na vitrine/README.

- Ícone do tray: ``tray.create_icon_image`` (Pillow puro).
- Splash: ``splash._render_splash`` (Pillow puro).
- Janela "Sobre": monkeypatch em ``about._pil_to_hbitmap`` para capturar a
  imagem PIL já desenhada e abortar antes de criar a janela Win32.

Uso (a partir da pasta ``like-move``):
    python assets/generate_previews.py
"""

import os
import sys

# Garante que o pacote like_move seja importável ao rodar o script direto
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)  # pasta "like-move"
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PIL import Image  # noqa: E402

OUT_DIR = os.path.join(_ROOT, "site", "assets")


def _save(img: Image.Image, name: str, scale: int = 1) -> None:
    if scale != 1:
        img = img.resize(
            (img.width * scale, img.height * scale), Image.Resampling.NEAREST
        )
    path = os.path.join(OUT_DIR, name)
    img.save(path)
    print(f"  ✓ {name} ({img.width}x{img.height})")


def gen_tray_icons() -> None:
    from like_move.tray import create_icon_image

    _save(create_icon_image(enabled=True), "tray-active.png", scale=4)
    _save(create_icon_image(enabled=False), "tray-paused.png", scale=4)


def gen_splash() -> None:
    from like_move import splash

    _save(splash._render_splash(), "splash.png")


def gen_about() -> None:
    """Captura a imagem real do 'Sobre' sem criar a janela."""
    from like_move import about

    captured: dict[str, Image.Image] = {}
    original = about._pil_to_hbitmap

    def _capture(img: Image.Image) -> int:
        captured["img"] = img.copy()
        return 0  # falsy → _show_about_impl retorna antes de criar a janela

    about._pil_to_hbitmap = _capture  # type: ignore[assignment]
    try:
        about._show_about_impl(icon=None)
    finally:
        about._pil_to_hbitmap = original  # type: ignore[assignment]

    if "img" not in captured:
        raise RuntimeError("Falha ao capturar a imagem do 'Sobre'")
    _save(captured["img"], "about.png")


def gen_app_icon() -> None:
    """PNG do ícone do app (para a logo da vitrine)."""
    ico_path = os.path.join(_ROOT, "assets", "like-move.ico")
    try:
        ico = Image.open(ico_path)
        if ico.mode != "RGBA":
            ico = ico.convert("RGBA")
        ico = ico.resize((128, 128), Image.Resampling.LANCZOS)
        _save(ico, "icon-128.png")
    except Exception as exc:  # pragma: no cover
        print(f"  ! ícone do app indisponível: {exc}")


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Gerando previews em {OUT_DIR}")
    gen_tray_icons()
    gen_splash()
    gen_about()
    gen_app_icon()
    print("OK")


if __name__ == "__main__":
    main()
