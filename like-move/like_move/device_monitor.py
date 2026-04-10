"""Device detection via Win32 API (ctypes) for KVM trigger mode.

Event-driven detection using WM_DEVICECHANGE with a hidden window
and message pump. Compares device counts against a baseline to
detect disconnections.
"""

import ctypes
import ctypes.wintypes
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Win32 DLLs
# ---------------------------------------------------------------------------
user32 = ctypes.windll.user32  # type: ignore[attr-defined]
kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Constants — Device detection
# ---------------------------------------------------------------------------
SM_CMONITORS: int = 80

RIM_TYPEMOUSE: int = 0
RIM_TYPEKEYBOARD: int = 1

# ---------------------------------------------------------------------------
# Constants — WM_DEVICECHANGE
# ---------------------------------------------------------------------------
WM_DEVICECHANGE: int = 0x0219
WM_DESTROY: int = 0x0002
WM_QUIT: int = 0x0012

DBT_DEVICEARRIVAL: int = 0x8000
DBT_DEVICEREMOVECOMPLETE: int = 0x8004
DBT_DEVNODES_CHANGED: int = 0x0007

WS_OVERLAPPED: int = 0x00000000

# WNDPROC callback type — LRESULT represented as LPARAM (both are LONG_PTR)
WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.wintypes.LPARAM,     # LRESULT
    ctypes.wintypes.HWND,       # hWnd
    ctypes.c_uint,              # uMsg
    ctypes.wintypes.WPARAM,     # wParam
    ctypes.wintypes.LPARAM,     # lParam
)


# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------
class RAWINPUTDEVICELIST(ctypes.Structure):
    """RAWINPUTDEVICELIST — handle + device type."""

    _fields_ = [
        ("hDevice", ctypes.wintypes.HANDLE),
        ("dwType", ctypes.wintypes.DWORD),
    ]


class WNDCLASSEXW(ctypes.Structure):
    """WNDCLASSEXW structure for RegisterClassExW."""

    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("style", ctypes.c_uint),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.wintypes.HINSTANCE),
        ("hIcon", ctypes.wintypes.HICON),
        ("hCursor", ctypes.wintypes.HANDLE),
        ("hbrBackground", ctypes.wintypes.HANDLE),
        ("lpszMenuName", ctypes.wintypes.LPCWSTR),
        ("lpszClassName", ctypes.wintypes.LPCWSTR),
        ("hIconSm", ctypes.wintypes.HICON),
    ]


class MSG(ctypes.Structure):
    """MSG structure for GetMessageW."""

    _fields_ = [
        ("hwnd", ctypes.wintypes.HWND),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.wintypes.WPARAM),
        ("lParam", ctypes.wintypes.LPARAM),
        ("time", ctypes.wintypes.DWORD),
        ("pt", ctypes.wintypes.POINT),
    ]


# ---------------------------------------------------------------------------
# Win32 function prototypes — Device detection
# ---------------------------------------------------------------------------
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int

user32.GetRawInputDeviceList.argtypes = [
    ctypes.POINTER(RAWINPUTDEVICELIST),
    ctypes.POINTER(ctypes.c_uint),
    ctypes.c_uint,
]
user32.GetRawInputDeviceList.restype = ctypes.c_uint

# ---------------------------------------------------------------------------
# Win32 function prototypes — Window / Message pump
# ---------------------------------------------------------------------------
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = ctypes.wintypes.ATOM

user32.UnregisterClassW.argtypes = [
    ctypes.wintypes.LPCWSTR,
    ctypes.wintypes.HINSTANCE,
]
user32.UnregisterClassW.restype = ctypes.wintypes.BOOL

user32.CreateWindowExW.argtypes = [
    ctypes.wintypes.DWORD,      # dwExStyle
    ctypes.wintypes.LPCWSTR,    # lpClassName
    ctypes.wintypes.LPCWSTR,    # lpWindowName
    ctypes.wintypes.DWORD,      # dwStyle
    ctypes.c_int,               # X
    ctypes.c_int,               # Y
    ctypes.c_int,               # nWidth
    ctypes.c_int,               # nHeight
    ctypes.wintypes.HWND,       # hWndParent
    ctypes.wintypes.HMENU,      # hMenu
    ctypes.wintypes.HINSTANCE,  # hInstance
    ctypes.wintypes.LPVOID,     # lpParam
]
user32.CreateWindowExW.restype = ctypes.wintypes.HWND

user32.DestroyWindow.argtypes = [ctypes.wintypes.HWND]
user32.DestroyWindow.restype = ctypes.wintypes.BOOL

user32.DefWindowProcW.argtypes = [
    ctypes.wintypes.HWND,
    ctypes.c_uint,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
]
user32.DefWindowProcW.restype = ctypes.wintypes.LPARAM

user32.GetMessageW.argtypes = [
    ctypes.POINTER(MSG),
    ctypes.wintypes.HWND,
    ctypes.c_uint,
    ctypes.c_uint,
]
user32.GetMessageW.restype = ctypes.wintypes.BOOL

user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.TranslateMessage.restype = ctypes.wintypes.BOOL

user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = ctypes.wintypes.LPARAM

user32.PostThreadMessageW.argtypes = [
    ctypes.wintypes.DWORD,      # idThread
    ctypes.c_uint,              # Msg
    ctypes.wintypes.WPARAM,     # wParam
    ctypes.wintypes.LPARAM,     # lParam
]
user32.PostThreadMessageW.restype = ctypes.wintypes.BOOL

kernel32.GetModuleHandleW.argtypes = [ctypes.wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = ctypes.wintypes.HMODULE

kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = ctypes.wintypes.DWORD


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------
def get_monitor_count() -> int:
    """Return the number of active display monitors via GetSystemMetrics."""
    count: int = user32.GetSystemMetrics(SM_CMONITORS)
    return max(count, 0)


def get_input_device_counts() -> dict[str, int]:
    """Return counts of mouse and keyboard devices via GetRawInputDeviceList.

    Uses the two-phase call pattern: first call with NULL to get the count,
    then allocate and fill the array. Retries on ERROR_INSUFFICIENT_BUFFER.
    """
    result: dict[str, int] = {"mouse": 0, "keyboard": 0}

    for _attempt in range(3):
        num_devices = ctypes.c_uint(0)
        cb_size = ctypes.c_uint(ctypes.sizeof(RAWINPUTDEVICELIST))

        # Phase 1: get device count
        ret = user32.GetRawInputDeviceList(
            None, ctypes.byref(num_devices), cb_size
        )
        if ret == ctypes.c_uint(-1).value:
            logger.warning("GetRawInputDeviceList phase 1 failed")
            return result

        if num_devices.value == 0:
            return result

        # Phase 2: fill array
        DeviceArray = RAWINPUTDEVICELIST * num_devices.value
        devices = DeviceArray()

        ret = user32.GetRawInputDeviceList(
            devices, ctypes.byref(num_devices), cb_size
        )
        if ret == ctypes.c_uint(-1).value:
            # Buffer may be insufficient if devices changed — retry
            continue

        # Count by type
        mouse_count = 0
        keyboard_count = 0
        for i in range(ret):
            if devices[i].dwType == RIM_TYPEMOUSE:
                mouse_count += 1
            elif devices[i].dwType == RIM_TYPEKEYBOARD:
                keyboard_count += 1

        result["mouse"] = mouse_count
        result["keyboard"] = keyboard_count
        return result

    logger.warning("GetRawInputDeviceList failed after retries")
    return result


# ---------------------------------------------------------------------------
# DeviceBaseline — tracks device counts for disconnect detection
# ---------------------------------------------------------------------------
class DeviceBaseline:
    """Captures and compares device counts to detect disconnections.

    On creation, captures current device counts as baseline.
    Subsequent calls to ``has_disconnection()`` compare current counts
    against the baseline to detect drops (= device unplugged).
    """

    def __init__(self) -> None:
        self._monitor_count: int = get_monitor_count()
        input_counts = get_input_device_counts()
        self._mouse_count: int = input_counts["mouse"]
        self._keyboard_count: int = input_counts["keyboard"]
        logger.info(
            "Device baseline captured: monitors=%d, mice=%d, keyboards=%d",
            self._monitor_count,
            self._mouse_count,
            self._keyboard_count,
        )

    def has_disconnection(self, monitor_devices: set[str]) -> bool:
        """Check if any monitored device count dropped below baseline.

        Args:
            monitor_devices: Set of device types to check.
                Valid values: ``"monitor"``, ``"mouse"``, ``"keyboard"``.

        Returns:
            True if at least one monitored device count is below baseline.
        """
        if "monitor" in monitor_devices:
            current_monitors = get_monitor_count()
            if current_monitors < self._monitor_count:
                return True

        if "mouse" in monitor_devices or "keyboard" in monitor_devices:
            input_counts = get_input_device_counts()
            if "mouse" in monitor_devices:
                if input_counts["mouse"] < self._mouse_count:
                    return True
            if "keyboard" in monitor_devices:
                if input_counts["keyboard"] < self._keyboard_count:
                    return True

        return False

    def refresh(self) -> None:
        """Update baseline to current device counts.

        Call this when devices reconnect so the baseline reflects
        the new normal state.
        """
        self._monitor_count = get_monitor_count()
        input_counts = get_input_device_counts()
        self._mouse_count = input_counts["mouse"]
        self._keyboard_count = input_counts["keyboard"]


# ---------------------------------------------------------------------------
# DeviceMonitor — event-driven device change detection
# ---------------------------------------------------------------------------
class DeviceMonitor:
    """Event-driven device disconnection monitor using WM_DEVICECHANGE.

    Creates a hidden top-level window with a message pump in a dedicated
    thread to receive device change broadcast notifications from Windows.
    Compares device counts against a baseline to detect disconnections.

    Note: message-only windows (HWND_MESSAGE) do NOT receive broadcast
    messages like WM_DEVICECHANGE, so a hidden top-level window is used.
    """

    _CLASS_NAME = "LikeMoveDeviceMonitor"

    def __init__(self, monitor_devices: set[str]) -> None:
        self._monitor_devices = set(monitor_devices)
        self._baseline = DeviceBaseline()
        self._disconnected = threading.Event()
        self._ready = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None
        self._hwnd: Optional[int] = None
        self._atom: Optional[int] = None
        self._hinstance: Optional[int] = None
        # prevent GC of the ctypes callback
        self._wndproc_ref: Optional[WNDPROC] = None

    def start(self) -> None:
        """Start the message pump thread."""
        if self._thread is not None:
            return
        self._disconnected.clear()
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run_message_pump,
            daemon=True,
            name="like-move-device-monitor",
        )
        self._thread.start()
        self._ready.wait(timeout=5.0)

    def stop(self) -> None:
        """Stop the message pump and clean up resources."""
        if self._thread is None:
            return
        if self._thread_id is not None:
            user32.PostThreadMessageW(
                ctypes.wintypes.DWORD(self._thread_id),
                ctypes.c_uint(WM_QUIT),
                ctypes.wintypes.WPARAM(0),
                ctypes.wintypes.LPARAM(0),
            )
        self._thread.join(timeout=5.0)
        self._thread = None
        self._thread_id = None

    @property
    def device_disconnected(self) -> bool:
        """True if a monitored device has disconnected. Thread-safe."""
        return self._disconnected.is_set()

    def refresh_baseline(self) -> None:
        """Recapture baseline and clear disconnection flag."""
        self._baseline.refresh()
        self._disconnected.clear()
        logger.info("Device monitor baseline refreshed")

    def update_monitor_devices(self, monitor_devices: set[str]) -> None:
        """Update the set of monitored device types and refresh baseline."""
        self._monitor_devices = set(monitor_devices)
        self.refresh_baseline()

    def _check_devices(self) -> None:
        """Compare current device counts against baseline and update flag."""
        if self._baseline.has_disconnection(self._monitor_devices):
            if not self._disconnected.is_set():
                logger.info("Device disconnection detected")
                self._disconnected.set()
        else:
            if self._disconnected.is_set():
                logger.info("Devices reconnected — clearing flag")
                self._disconnected.clear()
            self._baseline.refresh()

    def _wndproc(
        self,
        hwnd: int,
        msg: int,
        wparam: int,
        lparam: int,
    ) -> int:
        """Window procedure handling WM_DEVICECHANGE events."""
        if msg == WM_DEVICECHANGE:
            if wparam in (
                DBT_DEVICEREMOVECOMPLETE,
                DBT_DEVNODES_CHANGED,
                DBT_DEVICEARRIVAL,
            ):
                logger.debug("WM_DEVICECHANGE wParam=0x%04X", wparam)
                self._check_devices()
            return 0

        if msg == WM_DESTROY:
            return 0

        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run_message_pump(self) -> None:
        """Register window class, create hidden window, run message loop."""
        self._thread_id = kernel32.GetCurrentThreadId()
        self._hinstance = kernel32.GetModuleHandleW(None)

        self._wndproc_ref = WNDPROC(self._wndproc)

        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.style = 0
        wc.lpfnWndProc = self._wndproc_ref
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = self._hinstance
        wc.hIcon = None
        wc.hCursor = None
        wc.hbrBackground = None
        wc.lpszMenuName = None
        wc.lpszClassName = self._CLASS_NAME
        wc.hIconSm = None

        self._atom = user32.RegisterClassExW(ctypes.byref(wc))
        if not self._atom:
            logger.error("RegisterClassExW failed")
            self._ready.set()
            return

        # Hidden top-level window (NOT HWND_MESSAGE — broadcast messages
        # like WM_DEVICECHANGE are not delivered to message-only windows)
        self._hwnd = user32.CreateWindowExW(
            0,                          # dwExStyle
            self._CLASS_NAME,           # lpClassName
            "LikeMoveDeviceMonitor",    # lpWindowName
            WS_OVERLAPPED,             # dwStyle (no WS_VISIBLE)
            0, 0, 0, 0,               # x, y, width, height
            None,                       # hWndParent
            None,                       # hMenu
            self._hinstance,            # hInstance
            None,                       # lpParam
        )

        if not self._hwnd:
            logger.error("CreateWindowExW failed")
            user32.UnregisterClassW(self._CLASS_NAME, self._hinstance)
            self._atom = None
            self._ready.set()
            return

        logger.info("Device monitor started (event-driven)")
        self._ready.set()

        # Message pump — blocks until WM_QUIT
        msg = MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        # Cleanup
        if self._hwnd:
            user32.DestroyWindow(self._hwnd)
            self._hwnd = None
        if self._atom and self._hinstance:
            user32.UnregisterClassW(self._CLASS_NAME, self._hinstance)
            self._atom = None

        logger.info("Device monitor message pump stopped")
