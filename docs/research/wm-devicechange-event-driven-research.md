# Research: Refactoring device_monitor.py from Polling to Event-Driven via WM_DEVICECHANGE

**Date:** 2026-04-10
**Status:** Research Complete — Ready for Implementation
**Scope:** Replace 1-second polling loop in `device_monitor.py` with Windows event-driven `WM_DEVICECHANGE` notifications

---

## 1. Current Architecture Analysis

### Polling Model (Current)
```
MonitorThread (jiggler.py)
  └── Every 1 second:
        ├── DeviceBaseline.has_disconnection(monitor_devices)
        │     ├── GetSystemMetrics(SM_CMONITORS)       ← Win32 call per cycle
        │     └── GetRawInputDeviceList()               ← Win32 call per cycle
        ├── If disconnected → jiggle_mouse()
        └── If not disconnected → DeviceBaseline.refresh()
```

**Problem:** CPU cost of polling Win32 APIs every 1 second even when using the notebook normally (no KVM scenario). The polling is unnecessary when no device changes happen.

### Files Involved
| File | Role | Impact |
|------|------|--------|
| `device_monitor.py` | Device counting + baseline comparison | **MAJOR REWRITE** |
| `jiggler.py` | MonitorThread consumes DeviceBaseline | **MODERATE** — read flag instead of call API |
| `tray.py` | Creates MonitorThread, handles mode changes | **MINOR** — manage DeviceMonitor lifecycle |
| `config.py` | TriggerMode, JigglerState | **NO CHANGES** |
| `detector.py` | Idle time, screen lock detection | **NO CHANGES** |

---

## 2. Win32 API Research: WM_DEVICECHANGE

### Source: [Microsoft Docs — WM_DEVICECHANGE](https://learn.microsoft.com/en-us/windows/win32/devio/wm-devicechange)

**WM_DEVICECHANGE** notifies applications of hardware configuration changes via the window procedure (WNDPROC). Key events:

| Event | Value | Description | Broadcast? | Needs RegisterDeviceNotification? |
|-------|-------|-------------|------------|----------------------------------|
| `DBT_DEVNODES_CHANGED` | 0x0007 | Device added/removed from system | **Yes** | **No** |
| `DBT_DEVICEARRIVAL` | 0x8000 | Device inserted and available | Partial | Yes (for specific interfaces) |
| `DBT_DEVICEREMOVECOMPLETE` | 0x8004 | Device removed | Partial | Yes (for specific interfaces) |
| `DBT_CONFIGCHANGED` | 0x0018 | Configuration changed (dock/undock) | Yes | No |

### Decision: Use DBT_DEVNODES_CHANGED Only

**Rationale:**
- `DBT_DEVNODES_CHANGED` is **always broadcast to all top-level windows** — no registration needed
- It fires for ANY device tree change (monitors, mice, keyboards, USB hubs, etc.)
- Our WNDPROC simply re-counts devices using existing `get_monitor_count()` / `get_input_device_counts()` and compares with baseline
- No need for `RegisterDeviceNotification` — eliminates complexity of device class GUIDs and `DEV_BROADCAST_DEVICEINTERFACE`
- `DBT_DEVICEARRIVAL` / `DBT_DEVICEREMOVECOMPLETE` provide device-specific info we don't need (we count totals, not track individual devices)

**Trade-off:** `DBT_DEVNODES_CHANGED` may fire multiple times for a single physical event (e.g., USB hub reconnect triggers events for each device). This is fine — re-counting is idempotent and cheap.

---

## 3. Critical Finding: HWND_MESSAGE Does NOT Work

### Source: [Microsoft Docs — Window Features: Message-Only Windows](https://learn.microsoft.com/en-us/windows/win32/winmsg/window-features)

> "A message-only window enables you to send and receive messages. It is not visible, has no z-order, cannot be enumerated, and **does not receive broadcast messages**."

**WM_DEVICECHANGE with DBT_DEVNODES_CHANGED is a broadcast message.** Therefore, message-only windows (`HWND_MESSAGE` parent) will **NOT** receive it.

### Solution: Hidden Top-Level Window

Use a standard top-level window that is never made visible:

```
CreateWindowExW(
    dwExStyle  = 0,
    lpClassName = registered_class_atom,
    lpWindowName = "LikeMoveDeviceMonitor",
    dwStyle    = 0,          # No WS_VISIBLE, no WS_OVERLAPPED needed
    X, Y       = 0, 0,
    nWidth     = 0,
    nHeight    = 0,
    hWndParent = None,       # NOT HWND_MESSAGE — must be top-level
    hMenu      = None,
    hInstance  = GetModuleHandleW(None),
    lpParam    = None,
)
```

This creates an invisible, zero-size top-level window that:
- ✅ Receives broadcast messages (WM_DEVICECHANGE)
- ✅ Does not appear in taskbar
- ✅ Does not appear in Alt+Tab
- ✅ Consumes minimal resources

---

## 4. Win32 API Details for Implementation

### 4.1 Window Class Registration — RegisterClassExW

**Source:** [Microsoft Docs — RegisterClassExW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerclassexw)

```
WNDCLASSEXW structure:
  cbSize        = sizeof(WNDCLASSEXW)  # 80 bytes on 64-bit
  style         = 0
  lpfnWndProc   = WNDPROC callback     # ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)
  cbClsExtra    = 0
  cbWndExtra    = 0
  hInstance     = GetModuleHandleW(None)
  hIcon         = None
  hCursor       = None
  hbrBackground = None
  lpszMenuName  = None
  lpszClassName = "LikeMoveDeviceMonitorClass"  # Unique class name
  hIconSm       = None
```

**Important:** Must keep a Python reference to the WNDPROC callback to prevent garbage collection.

### 4.2 Message Pump — GetMessageW Loop

**Source:** [Microsoft Docs — GetMessageW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getmessagew)

```
while True:
    ret = GetMessageW(byref(msg), None, 0, 0)
    if ret == 0:    # WM_QUIT received
        break
    if ret == -1:   # Error
        break
    TranslateMessage(byref(msg))
    DispatchMessageW(byref(msg))
```

**Key behavior:**
- `GetMessageW` blocks until a message is available (zero CPU when idle)
- Returns 0 on `WM_QUIT` — clean exit
- Returns -1 on error (invalid HWND)
- `DispatchMessageW` calls the WNDPROC for window messages

### 4.3 Graceful Shutdown — PostThreadMessage

To stop the message pump from another thread:

```
PostThreadMessage(native_thread_id, WM_QUIT, 0, 0)
```

**Getting the native thread ID:**
- Python 3.8+: `thread.native_id` (set after thread starts)
- Alternative: Call `GetCurrentThreadId()` from within the thread and store it

### 4.4 Cleanup Sequence

Must be done from the message pump thread (same thread that created the window):

1. `DestroyWindow(hwnd)` — destroys the window
2. `UnregisterClassW(class_name, hinstance)` — unregisters the window class

---

## 5. Proposed Architecture

### New Thread Model

```
Main Thread (pystray)
  ├── TrayApp manages lifecycle
  │
  ├── MonitorThread (jiggler.py) — existing polling loop
  │     └── Every 1 second:
  │           ├── Check idle time (unchanged)
  │           ├── Check device_monitor.device_disconnected (flag read, NO Win32 call)
  │           └── Jiggle if triggered
  │
  └── DeviceMonitor._thread (NEW — device_monitor.py)
        ├── Create hidden top-level window
        ├── Capture baseline (get_monitor_count + get_input_device_counts)
        ├── Run GetMessageW loop (blocks, zero CPU when idle)
        ├── On WM_DEVICECHANGE:
        │     ├── Re-count devices
        │     ├── Compare with baseline
        │     ├── Set/clear threading.Event flag
        │     └── Refresh baseline if devices restored
        └── On WM_QUIT: cleanup (DestroyWindow, UnregisterClass)
```

### CPU Savings

| Scenario | Current (Polling) | Proposed (Event-Driven) |
|----------|-------------------|------------------------|
| No device changes | 1 GetSystemMetrics + 1 GetRawInputDeviceList per second | **Zero Win32 calls** |
| Device disconnects | Same as above | 1 re-count on event only |
| Normal laptop use (no KVM) | Continuous polling | **Completely idle** |

### DeviceMonitor Class Interface

```
class DeviceMonitor:
    def __init__(self, monitor_devices: set[str]):
        # Captures baseline, creates thread (but does NOT start it)
    
    def start(self) -> None:
        # Starts the message pump thread
    
    def stop(self) -> None:
        # Posts WM_QUIT, joins thread, cleanup complete
    
    @property
    def device_disconnected(self) -> bool:
        # Thread-safe read — True if device count dropped below baseline
        # Backed by threading.Event
    
    def refresh_baseline(self) -> None:
        # Thread-safe baseline update (called when mode/devices change)
```

### Thread Safety Model

- **`threading.Event`** for `_disconnected` flag:
  - Set by WNDPROC thread (on WM_DEVICECHANGE when count drops)
  - Cleared by WNDPROC thread (on WM_DEVICECHANGE when count restores)
  - Read by MonitorThread via `device_disconnected` property (Event.is_set())
  - Thread-safe by design (Event is internally synchronized)

- **`threading.Lock`** for baseline data:
  - Baseline counts read/written by WNDPROC thread
  - `refresh_baseline()` may be called from tray thread (on mode change)
  - Lock protects the three count fields

---

## 6. Implementation Plan

### Step 1: Refactor `device_monitor.py` (MAJOR)

**Keep:**
- `RAWINPUTDEVICELIST` structure
- `get_monitor_count()` function
- `get_input_device_counts()` function
- `DeviceBaseline` class (used internally by DeviceMonitor)

**Add:**
- Win32 constants: WM_DEVICECHANGE, DBT_DEVNODES_CHANGED, WM_QUIT, etc.
- Win32 structures: WNDCLASSEXW, MSG
- Win32 function prototypes: RegisterClassExW, CreateWindowExW, GetMessageW, TranslateMessage, DispatchMessageW, PostThreadMessage, DestroyWindow, UnregisterClassW, GetModuleHandleW, DefWindowProcW
- WNDPROC callback via `ctypes.WINFUNCTYPE`
- `DeviceMonitor` class with hidden window + message pump thread

**Remove:**
- Nothing — all existing functions preserved as utilities

### Step 2: Adjust `jiggler.py` (MODERATE)

**Changes in MonitorThread:**
- Remove `_device_baseline: Optional[DeviceBaseline]` field
- Add `_device_monitor: Optional[DeviceMonitor]` field  
- In `_check_and_jiggle()` KVM block: read `_device_monitor.device_disconnected` instead of calling `has_disconnection()`
- Remove `refresh()` call — DeviceMonitor handles this internally
- In `reset_device_baseline()`: call `_device_monitor.refresh_baseline()` instead of `self._device_baseline = None`
- Lifecycle: create/start DeviceMonitor when KVM mode activates, stop when it deactivates

**Alternative approach (simpler):** MonitorThread receives DeviceMonitor reference from tray, doesn't manage lifecycle.

### Step 3: Adjust `tray.py` (MINOR)

**Changes:**
- Create `DeviceMonitor(monitor_devices)` when trigger_mode includes KVM
- Stop DeviceMonitor when mode changes away from KVM
- Pass DeviceMonitor reference to MonitorThread
- On device toggle: stop old DeviceMonitor, create new one with updated device set
- On quit: stop DeviceMonitor before stopping MonitorThread

---

## 7. Risks and Mitigations

### Risk 1: DBT_DEVNODES_CHANGED Noise
**Problem:** May fire multiple times per physical event (USB hub enumeration).
**Mitigation:** Re-counting is idempotent. Multiple re-counts produce the same result. No debouncing needed.

### Risk 2: WNDPROC Callback Garbage Collection
**Problem:** If Python garbage-collects the ctypes callback, the window procedure pointer becomes dangling.
**Mitigation:** Store the callback as an instance attribute of DeviceMonitor (`self._wndproc_callback = WNDPROC(self._window_proc)`). Instance lives as long as monitor is running.

### Risk 3: Thread Cleanup Order
**Problem:** `DestroyWindow` must be called from the thread that created the window. `UnregisterClass` must be called after `DestroyWindow`.
**Mitigation:** Perform cleanup inside the message pump thread, after `GetMessageW` returns 0 (WM_QUIT). Sequence: DestroyWindow → process remaining messages → UnregisterClass.

### Risk 4: Race Between stop() and WM_DEVICECHANGE
**Problem:** WM_DEVICECHANGE arrives between `PostThreadMessage(WM_QUIT)` and actual thread exit.
**Mitigation:** The WNDPROC still processes the message (harmless — sets a flag on a monitor about to be destroyed). Thread joins after WM_QUIT processed.

### Risk 5: Monitor Display Changes via WM_DISPLAYCHANGE
**Problem:** Monitor connect/disconnect may also send `WM_DISPLAYCHANGE` (resolution/count change). Should we handle it?
**Mitigation:** `DBT_DEVNODES_CHANGED` already covers device tree changes including monitors. `WM_DISPLAYCHANGE` is redundant for our use case. Can optionally add as secondary trigger if `DBT_DEVNODES_CHANGED` proves unreliable for monitor changes.

### Risk 6: PostThreadMessage Before Message Loop Starts
**Problem:** If `stop()` is called before the thread's `GetMessageW` loop begins, `PostThreadMessage` may fail.
**Mitigation:** Use a `threading.Event` (`_ready`) set by the message pump thread after window creation. `stop()` waits on `_ready` before posting WM_QUIT.

### Risk 7: ALWAYS Mode Still Needs Polling
**Problem:** ALWAYS and IDLE modes don't use device monitoring. DeviceMonitor should only run when mode includes KVM.
**Mitigation:** Create/start DeviceMonitor only for KVM and BOTH modes. Stop it when switching to IDLE or ALWAYS.

---

## 8. Dependencies

- **No new dependencies** — all via ctypes (user32.dll, kernel32.dll)
- **No pywin32** — pure ctypes
- **No admin privileges** — `WM_DEVICECHANGE` broadcast received by normal user processes
- **Python 3.8+** — for `threading.Thread.native_id` (already required by project)

---

## 9. Testing Strategy

- **Manual test:** Run like-move in KVM mode, disconnect USB mouse → verify jiggle triggers
- **Manual test:** Reconnect mouse → verify jiggle stops
- **Manual test:** Switch to IDLE mode → verify DeviceMonitor thread stops (no window in memory)
- **Manual test:** CPU usage comparison: old polling vs new event-driven (Task Manager)
- **Unit test opportunity:** Mock `get_monitor_count()` / `get_input_device_counts()` to simulate disconnection

---

## 10. Key API Reference Summary

| API | DLL | Purpose | ctypes Signature |
|-----|-----|---------|-----------------|
| `RegisterClassExW` | user32 | Register window class | `(POINTER(WNDCLASSEXW)) → ATOM` |
| `UnregisterClassW` | user32 | Unregister window class | `(LPCWSTR, HINSTANCE) → BOOL` |
| `CreateWindowExW` | user32 | Create hidden window | `(DWORD, LPCWSTR, LPCWSTR, DWORD, int, int, int, int, HWND, HMENU, HINSTANCE, LPVOID) → HWND` |
| `DestroyWindow` | user32 | Destroy window | `(HWND) → BOOL` |
| `GetMessageW` | user32 | Blocking message retrieval | `(POINTER(MSG), HWND, UINT, UINT) → BOOL` |
| `TranslateMessage` | user32 | Translate virtual-key messages | `(POINTER(MSG)) → BOOL` |
| `DispatchMessageW` | user32 | Dispatch message to WNDPROC | `(POINTER(MSG)) → LRESULT` |
| `PostThreadMessage` | user32 | Post message to thread queue | `(DWORD, UINT, WPARAM, LPARAM) → BOOL` |
| `DefWindowProcW` | user32 | Default message processing | `(HWND, UINT, WPARAM, LPARAM) → LRESULT` |
| `GetModuleHandleW` | kernel32 | Get module instance handle | `(LPCWSTR) → HMODULE` |
| `GetCurrentThreadId` | kernel32 | Get native thread ID | `() → DWORD` |
