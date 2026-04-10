"""Device detection via Win32 API (ctypes) for KVM trigger mode.

Detects monitor/mouse/keyboard disconnection by polling device counts
and comparing against a baseline captured at startup or mode switch.
"""

import ctypes
import ctypes.wintypes
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Win32 DLLs
# ---------------------------------------------------------------------------
user32 = ctypes.windll.user32  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SM_CMONITORS: int = 80

RIM_TYPEMOUSE: int = 0
RIM_TYPEKEYBOARD: int = 1


# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------
class RAWINPUTDEVICELIST(ctypes.Structure):
    """RAWINPUTDEVICELIST — handle + device type."""

    _fields_ = [
        ("hDevice", ctypes.wintypes.HANDLE),
        ("dwType", ctypes.wintypes.DWORD),
    ]


# ---------------------------------------------------------------------------
# Win32 function prototypes
# ---------------------------------------------------------------------------
# int GetSystemMetrics(int nIndex)
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int

# UINT GetRawInputDeviceList(
#   PRAWINPUTDEVICELIST pRawInputDeviceList,
#   PUINT              puiNumDevices,
#   UINT               cbSize
# )
user32.GetRawInputDeviceList.argtypes = [
    ctypes.POINTER(RAWINPUTDEVICELIST),
    ctypes.POINTER(ctypes.c_uint),
    ctypes.c_uint,
]
user32.GetRawInputDeviceList.restype = ctypes.c_uint


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
