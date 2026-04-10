"""Splash screen com animação fade via Win32 API + Pillow.

Cria uma janela layered sem borda (WS_POPUP + WS_EX_LAYERED) com
per-pixel alpha via UpdateLayeredWindow. A splash faz fade-in,
permanece visível por ~1.5 s, e faz fade-out. Total ~2.5 s.

Sem dependências novas — usa ctypes (stdlib) e Pillow (já existente).
"""

import ctypes
import ctypes.wintypes as wintypes
import logging
import os
import sys
import time

from PIL import Image, ImageDraw, ImageFont

from . import __version__

logger = logging.getLogger(__name__)

# ── Win32 DLLs ──────────────────────────────────────────────────────
user32 = ctypes.windll.user32  # type: ignore[attr-defined]
gdi32 = ctypes.windll.gdi32  # type: ignore[attr-defined]
kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

# ── Win32 constants ─────────────────────────────────────────────────
WS_POPUP: int = 0x80000000
WS_EX_LAYERED: int = 0x00080000
WS_EX_TOPMOST: int = 0x00000008
WS_EX_TOOLWINDOW: int = 0x00000080
SW_SHOWNOACTIVATE: int = 4
SM_CXSCREEN: int = 0
SM_CYSCREEN: int = 1
PM_REMOVE: int = 0x0001

AC_SRC_OVER: int = 0x00
AC_SRC_ALPHA: int = 0x01
ULW_ALPHA: int = 0x02
DIB_RGB_COLORS: int = 0
BI_RGB: int = 0

# Splash dimensions
SPLASH_W: int = 300
SPLASH_H: int = 200

# WNDPROC — same pattern as device_monitor.py (LRESULT as LPARAM)
WNDPROC = ctypes.WINFUNCTYPE(
    wintypes.LPARAM, wintypes.HWND,
    ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM,
)

# ── Win32 structures ────────────────────────────────────────────────


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("style", ctypes.c_uint),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


# ── Helpers ─────────────────────────────────────────────────────────


def _asset_path(filename: str) -> str:
    """Resolve asset path for both source and PyInstaller bundle."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", filename)


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, ...],
    canvas_w: int,
) -> None:
    """Draw horizontally-centered text on the canvas."""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((canvas_w - tw) // 2, y), text, fill=fill, font=font)


def _render_splash() -> Image.Image:
    """Render splash screen as RGBA image with Pillow."""
    w, h = SPLASH_W, SPLASH_H
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded rectangle background (#2ecc71 green)
    draw.rounded_rectangle(
        [(0, 0), (w - 1, h - 1)],
        radius=16,
        fill=(46, 204, 113, 230),
    )

    # App icon from assets
    try:
        ico = Image.open(_asset_path("like-move.ico"))
        ico = ico.resize((64, 64), Image.Resampling.LANCZOS)
        if ico.mode != "RGBA":
            ico = ico.convert("RGBA")
        img.paste(ico, ((w - 64) // 2, 24), ico)
    except Exception:
        logger.debug("Icon load failed for splash", exc_info=True)

    # Fonts (Segoe UI ships with Windows)
    try:
        font_title = ImageFont.truetype("segoeui.ttf", 28)
        font_sub = ImageFont.truetype("segoeui.ttf", 14)
    except OSError:
        font_title = ImageFont.load_default()
        font_sub = font_title

    _draw_centered(draw, "like-move", 96, font_title, (15, 80, 45, 255), w)
    _draw_centered(draw, f"v{__version__}", 130, font_sub, (15, 80, 45, 200), w)
    _draw_centered(draw, "Iniciando…", 160, font_sub, (15, 80, 45, 180), w)

    return img


def _pil_to_hbitmap(img: Image.Image) -> int:
    """Convert Pillow RGBA image to pre-multiplied-alpha Win32 HBITMAP."""
    w, h = img.size

    # DIB is bottom-up
    flipped = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    raw = bytearray(flipped.tobytes("raw", "BGRA"))

    # Pre-multiply alpha (required by UpdateLayeredWindow)
    for i in range(0, len(raw), 4):
        a = raw[i + 3]
        if a == 0:
            raw[i] = raw[i + 1] = raw[i + 2] = 0
        elif a < 255:
            raw[i] = raw[i] * a // 255
            raw[i + 1] = raw[i + 1] * a // 255
            raw[i + 2] = raw[i + 2] * a // 255

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB

    hdc = user32.GetDC(None)
    bits = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(
        hdc,
        ctypes.byref(bmi),
        DIB_RGB_COLORS,
        ctypes.byref(bits),
        None,
        0,
    )
    if hbmp and bits:
        ctypes.memmove(bits, bytes(raw), len(raw))
    user32.ReleaseDC(None, hdc)
    return hbmp


def _pump_messages() -> None:
    """Process pending Windows messages without blocking."""
    msg = wintypes.MSG()
    while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


# ── Public API ──────────────────────────────────────────────────────


def show_splash() -> None:
    """Show splash screen with fade animation (~2.5 s, blocking).

    Fails silently so the app always starts even if splash errors out.
    """
    try:
        _show_splash_impl()
    except Exception:
        logger.debug("Splash screen failed", exc_info=True)


def _show_splash_impl() -> None:
    """Create layered Win32 window, fade in → hold → fade out → destroy."""
    img = _render_splash()
    hbmp = _pil_to_hbitmap(img)
    if not hbmp:
        return

    # WNDPROC reference must outlive the window (prevent GC)
    wnd_proc = WNDPROC(
        lambda hwnd, msg, wp, lp: user32.DefWindowProcW(hwnd, msg, wp, lp)
    )
    hinstance = kernel32.GetModuleHandleW(None)
    cls_name = "LikeMoveSplash"

    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = wnd_proc
    wc.hInstance = hinstance
    wc.lpszClassName = cls_name

    if not user32.RegisterClassExW(ctypes.byref(wc)):
        gdi32.DeleteObject(hbmp)
        return

    # Center on primary monitor
    sx = user32.GetSystemMetrics(SM_CXSCREEN)
    sy = user32.GetSystemMetrics(SM_CYSCREEN)
    x = (sx - SPLASH_W) // 2
    y = (sy - SPLASH_H) // 2

    hwnd = user32.CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
        cls_name,
        "like-move",
        WS_POPUP,
        x,
        y,
        SPLASH_W,
        SPLASH_H,
        None,
        None,
        hinstance,
        None,
    )
    if not hwnd:
        gdi32.DeleteObject(hbmp)
        user32.UnregisterClassW(cls_name, hinstance)
        return

    # Prepare memory DC for UpdateLayeredWindow
    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    old_bmp = gdi32.SelectObject(hdc_mem, hbmp)

    pt_src = POINT(0, 0)
    pt_dst = POINT(x, y)
    sz = SIZE(SPLASH_W, SPLASH_H)

    def _update(alpha: int) -> None:
        bf = BLENDFUNCTION(AC_SRC_OVER, 0, alpha, AC_SRC_ALPHA)
        user32.UpdateLayeredWindow(
            hwnd,
            hdc_screen,
            ctypes.byref(pt_dst),
            ctypes.byref(sz),
            hdc_mem,
            ctypes.byref(pt_src),
            0,
            ctypes.byref(bf),
            ULW_ALPHA,
        )

    # Start invisible, then show
    _update(0)
    user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)

    fade_steps = 16
    fade_delay = 0.025  # seconds per step → ~400 ms per fade

    # Fade in (0 → 255)
    for i in range(1, fade_steps + 1):
        _update(min(255, 255 * i // fade_steps))
        _pump_messages()
        time.sleep(fade_delay)

    # Hold visible (~1.5 s), pumping messages to stay responsive
    for _ in range(15):
        _pump_messages()
        time.sleep(0.1)

    # Fade out (255 → 0)
    for i in range(fade_steps, -1, -1):
        _update(max(0, 255 * i // fade_steps))
        _pump_messages()
        time.sleep(fade_delay)

    # Cleanup GDI / window resources
    gdi32.SelectObject(hdc_mem, old_bmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(None, hdc_screen)
    user32.DestroyWindow(hwnd)
    gdi32.DeleteObject(hbmp)
    user32.UnregisterClassW(cls_name, hinstance)
