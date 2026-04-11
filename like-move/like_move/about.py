import ctypes
import ctypes.wintypes as wintypes
import logging
import os
import sys
import time

from PIL import Image, ImageDraw, ImageFont

from . import __version__

logger = logging.getLogger(__name__)

# ── Win32 DLLs (private instances to avoid argtypes conflicts with pystray) ──
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = wintypes.LPARAM

gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ── Win32 constants ─────────────────────────────────────────────────
WS_POPUP: int = 0x80000000
WS_EX_LAYERED: int = 0x00080000
WS_EX_TOPMOST: int = 0x00000008
WS_EX_TOOLWINDOW: int = 0x00000080
SW_SHOWNOACTIVATE: int = 4
PM_REMOVE: int = 0x0001

AC_SRC_OVER: int = 0x00
AC_SRC_ALPHA: int = 0x01
ULW_ALPHA: int = 0x02
DIB_RGB_COLORS: int = 0
BI_RGB: int = 0

# ── WNDPROC callback type ──────────────────────────────────────────
WNDPROC = ctypes.WINFUNCTYPE(
    wintypes.LPARAM, wintypes.HWND,
    ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM,
)

# ── Win32 structures (defined locally to avoid cross-module ctypes conflicts) ──


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


# ── Helpers (local copies — no imports from splash) ─────────────────


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


def _pil_to_hbitmap(img: Image.Image) -> int:
    """Convert Pillow RGBA image to pre-multiplied-alpha Win32 HBITMAP."""
    w, h = img.size

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


W: int = 420
H: int = 440


def show_about(icon=None) -> None:
    """Show a custom About window (layered) and block until closed.

    If an pystray Icon is passed, it will be hidden while the About window
    is visible to avoid interaction with the tray (modal behaviour).
    """
    try:
        _show_about_impl(icon)
    except Exception:
        logger.debug("About window failed", exc_info=True)


def _show_about_impl(icon) -> None:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background rounded rectangle
    draw.rounded_rectangle([(0, 0), (W - 1, H - 1)], radius=20, fill=(46, 204, 113, 230))

    # App icon
    try:
        ico = Image.open(_asset_path("like-move.ico"))
        ico = ico.resize((64, 64), Image.Resampling.LANCZOS)
        if ico.mode != "RGBA":
            ico = ico.convert("RGBA")
        img.paste(ico, (24, 24), ico)
    except Exception:
        logger.debug("Failed to load icon for About", exc_info=True)

    # Fonts
    try:
        font_title = ImageFont.truetype("segoeui.ttf", 26)
        font_sub = ImageFont.truetype("segoeui.ttf", 14)
    except OSError:
        font_title = ImageFont.load_default()
        font_sub = font_title

    # Title and version
    _draw_centered(draw, "like-move", 28, font_title, (15, 80, 45, 255), W)
    _draw_centered(draw, f"v{__version__}", 64, font_sub, (15, 80, 45, 200), W)

    # Body text (left-aligned)
    body = (
        "Mouse jiggler inteligente para Windows\n\n"
        "Como usar:\n"
        "• Clique direito no ícone para acessar o menu\n"
        "• Ativo: Liga/desliga o jiggler\n"
        "• Modo: Escolha entre Inatividade, KVM, Ambos ou Sempre\n"
        "• Threshold: Tempo de espera antes de começar (15s a 5min)\n"
        "• Dispositivos KVM: Escolha quais dispositivos monitorar\n\n"
        "Ícone verde = ativo | Ícone cinza = pausado\n"
    )
    # draw multiline text with some margin
    text_x = 24
    text_y = 110
    draw.multiline_text((text_x, text_y), body, font=font_sub, fill=(15, 80, 45, 220), spacing=4)

    # Draw clickable GitHub link separately (underlined, blue)
    link_text = "github.com/AllanSantos-DV/like-move"
    # compute body bbox to position link below body
    try:
        body_bbox = draw.multiline_textbbox((text_x, text_y), body, font=font_sub, spacing=4)
    except AttributeError:
        # older Pillow fallback: approximate by measuring last line
        last = body.splitlines()[-1]
        lb = draw.textbbox((text_x, text_y), last, font=font_sub)
        body_bbox = (lb[0], lb[1], lb[2], lb[3])
    link_x = text_x
    link_y = body_bbox[3] + 8
    draw.text((link_x, link_y), link_text, font=font_sub, fill=(10, 50, 120, 255))
    # underline
    lt_bbox = draw.textbbox((link_x, link_y), link_text, font=font_sub)
    draw.line([(lt_bbox[0], lt_bbox[3] + 2), (lt_bbox[2], lt_bbox[3] + 2)], fill=(10, 50, 120, 255), width=1)
    # save link rect for hit-testing
    link_rect = {"x1": lt_bbox[0], "y1": lt_bbox[1], "x2": lt_bbox[2], "y2": lt_bbox[3]}

    # OK button
    btn_w, btn_h = 120, 36
    btn_x1 = (W - btn_w) // 2
    btn_y1 = H - 64
    btn_x2 = btn_x1 + btn_w
    btn_y2 = btn_y1 + btn_h
    draw.rounded_rectangle([(btn_x1, btn_y1), (btn_x2, btn_y2)], radius=8, fill=(255, 255, 255, 255))
    # OK text
    try:
        font_btn = ImageFont.truetype("segoeui.ttf", 14)
    except OSError:
        font_btn = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), "OK", font=font_btn)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(((W - tw) // 2, btn_y1 + (btn_h - th) // 2), "OK", fill=(46, 204, 113, 255), font=font_btn)

    # Close X (draw simple X in top-right)
    x_margin = 18
    x_size = 12
    x_cx = W - x_margin
    x_cy = x_margin
    draw.line([(x_cx - x_size // 2, x_cy - x_size // 2), (x_cx + x_size // 2, x_cy + x_size // 2)], fill=(15, 80, 45, 220), width=2)
    draw.line([(x_cx + x_size // 2, x_cy - x_size // 2), (x_cx - x_size // 2, x_cy + x_size // 2)], fill=(15, 80, 45, 220), width=2)

    # Convert to HBITMAP
    hbmp = _pil_to_hbitmap(img)
    if not hbmp:
        return

    # WNDPROC
    clicked = {"down": False}

    def _wndproc(hwnd, msg, wp, lp):
        if msg == 0x0002:  # WM_DESTROY
            user32.PostQuitMessage(0)
            return 0
        if msg == 0x0201:  # WM_LBUTTONDOWN
            x = lp & 0xFFFF
            y = (lp >> 16) & 0xFFFF
            clicked["down"] = True
            clicked["x"] = x
            clicked["y"] = y
            return 0
        if msg == 0x0202 and clicked.get("down"):
            # WM_LBUTTONUP
            x = lp & 0xFFFF
            y = (lp >> 16) & 0xFFFF
            clicked["down"] = False
            # Check GitHub link
            try:
                if link_rect["x1"] <= x <= link_rect["x2"] and link_rect["y1"] <= y <= link_rect["y2"]:
                    import webbrowser
                    webbrowser.open("https://github.com/AllanSantos-DV/like-move")
                    return 0
            except Exception:
                pass
            # Check OK button
            if btn_x1 <= x <= btn_x2 and btn_y1 <= y <= btn_y2:
                user32.DestroyWindow(hwnd)
                return 0
            # Check close X (approx area 24x24 around x_cx,x_cy)
            if abs(x - x_cx) <= 12 and abs(y - x_cy) <= 12:
                user32.DestroyWindow(hwnd)
                return 0
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    wnd_proc = WNDPROC(_wndproc)
    hinstance = kernel32.GetModuleHandleW(None)
    cls_name = "LikeMoveAbout"

    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = wnd_proc
    wc.hInstance = hinstance
    # Ensure LoadCursorW has proper signatures and set the arrow cursor to avoid the loading cursor
    user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    user32.LoadCursorW.restype = wintypes.HANDLE
    wc.hCursor = user32.LoadCursorW(None, 32512)  # IDC_ARROW
    wc.lpszClassName = cls_name

    if not user32.RegisterClassExW(ctypes.byref(wc)):
        gdi32.DeleteObject(hbmp)
        return

    # Center on screen
    sx = user32.GetSystemMetrics(0)
    sy = user32.GetSystemMetrics(1)
    x = (sx - W) // 2
    y = (sy - H) // 2

    hwnd = user32.CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
        cls_name,
        "like-move",
        WS_POPUP,
        x,
        y,
        W,
        H,
        None,
        None,
        hinstance,
        None,
    )
    if not hwnd:
        gdi32.DeleteObject(hbmp)
        user32.UnregisterClassW(cls_name, hinstance)
        return

    # Prepare DCs
    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    old_bmp = gdi32.SelectObject(hdc_mem, hbmp)

    pt_src = POINT(0, 0)
    pt_dst = POINT(x, y)
    sz = SIZE(W, H)

    def _update():
        bf = BLENDFUNCTION(AC_SRC_OVER, 0, 255, 1)
        user32.UpdateLayeredWindow(hwnd, hdc_screen, ctypes.byref(pt_dst), ctypes.byref(sz), hdc_mem, ctypes.byref(pt_src), 0, ctypes.byref(bf), ULW_ALPHA)

    # Optionally hide tray icon to make modal
    try:
        if icon is not None:
            try:
                icon.visible = False
            except Exception:
                pass
    except Exception:
        pass

    _update()
    user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)

    # Message loop until window destroyed
    msg = wintypes.MSG()
    while user32.IsWindow(hwnd):
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.01)

    # Cleanup
    gdi32.SelectObject(hdc_mem, old_bmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(None, hdc_screen)
    gdi32.DeleteObject(hbmp)
    user32.UnregisterClassW(cls_name, hinstance)

    # Restore tray icon visibility
    try:
        if icon is not None:
            try:
                icon.visible = True
            except Exception:
                pass
    except Exception:
        pass
