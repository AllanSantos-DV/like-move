# Research: Configurable Trigger Modes for like-move

**Date:** 2026-04-10
**Topic:** Adding KVM device detection modes alongside existing idle detection

---

## 1. Current Architecture Analysis

### Codebase Structure
```
like-move/
├── main.pyw              # Entry point (pythonw)
├── requirements.txt      # pystray>=0.19.0, Pillow>=9.0.0
├── like_move/
│   ├── __init__.py       # v1.0.0
│   ├── config.py         # Constants + JigglerState dataclass
│   ├── detector.py       # get_idle_time_ms(), is_screen_locked() — ctypes Win32
│   ├── jiggler.py        # jiggle_mouse() + MonitorThread
│   └── tray.py           # TrayApp with pystray (menu: Ativo, Threshold, Sair)
```

### Current Flow
1. `main.pyw` → creates `TrayApp` → `app.run()` (blocking pystray loop)
2. `TrayApp._setup()` creates `MonitorThread(state)` as daemon thread
3. `MonitorThread._check_and_jiggle()` runs every 1s:
   - Skip if `state.enabled == False`
   - Skip if `is_screen_locked()` returns True
   - Skip if `get_idle_time_ms() < threshold * 1000`
   - Respect `jiggle_interval` between jiggles
   - Call `jiggle_mouse()` via SendInput

### JigglerState (config.py)
- `enabled: bool = True`
- `idle_threshold: int = 30` (seconds)
- `jiggle_interval: int = 10` (seconds)

---

## 2. Win32 APIs for Device Detection

### 2.1 Monitor Count: `GetSystemMetrics(SM_CMONITORS)`

- **Source:** https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getsystemmetrics
- **DLL:** User32.dll — already imported in detector.py
- **Constant:** `SM_CMONITORS = 80`
- **Signature:** `int GetSystemMetrics(int nIndex)`
- **Returns:** Number of display monitors currently active
- **Admin required:** NO
- **Complexity:** Trivial — single call, no structs needed
- **ctypes:** `user32.GetSystemMetrics(80)` → int
- **KVM detection strategy:** Poll every 1s. If count drops (e.g., 2→1 or 1→0), monitor was disconnected. When count restores, monitor reconnected.
- **Edge case:** SM_CMONITORS counts only physical display monitors, not pseudo-monitors. This is exactly what we want for KVM detection.

**Why GetSystemMetrics over EnumDisplayMonitors:**
- `EnumDisplayMonitors` requires a callback function (`MONITORENUMPROC`) via ctypes — complex to set up with `ctypes.CFUNCTYPE`
- `GetSystemMetrics(SM_CMONITORS)` is a single int return — trivially simple
- Both return the same count for physical monitors
- **Decision: Use GetSystemMetrics** — simpler, same result

### 2.2 Mouse/Keyboard Count: `GetRawInputDeviceList`

- **Source:** https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getrawinputdevicelist
- **DLL:** User32.dll
- **Admin required:** NO
- **Min OS:** Windows XP

**RAWINPUTDEVICELIST structure:**
```
typedef struct tagRAWINPUTDEVICELIST {
    HANDLE hDevice;   // device handle
    DWORD  dwType;    // RIM_TYPEMOUSE=0, RIM_TYPEKEYBOARD=1, RIM_TYPEHID=2
} RAWINPUTDEVICELIST;
```

**ctypes mapping:**
```python
class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [
        ("hDevice", ctypes.wintypes.HANDLE),
        ("dwType", ctypes.wintypes.DWORD),
    ]

RIM_TYPEMOUSE = 0
RIM_TYPEKEYBOARD = 1
RIM_TYPEHID = 2
```

**Usage pattern (two-phase call):**
1. Call with `pRawInputDeviceList=NULL` → get device count in `puiNumDevices`
2. Allocate array, call again to fill it
3. Filter by `dwType` to count mice vs keyboards

**KVM detection strategy:**
- Poll every 1s
- Count devices where `dwType == RIM_TYPEMOUSE` and `dwType == RIM_TYPEKEYBOARD`
- If count drops from baseline → device disconnected → trigger jiggle
- When count restores → device reconnected → stop jiggle

**Important caveat:** RDP devices do NOT appear in raw input device list. This is fine — KVM mode targets physical device switching, not RDP.

### 2.3 Event-Driven Alternative: `WM_DEVICECHANGE`

- **Source:** https://learn.microsoft.com/en-us/windows/win32/devio/wm-devicechange
- **Events relevant:**
  - `DBT_DEVICEARRIVAL` (0x8000) — device connected
  - `DBT_DEVICEREMOVECOMPLETE` (0x8004) — device removed
  - `DBT_DEVNODES_CHANGED` (0x0007) — generic device tree change
- **Requirements:**
  - A window (can be hidden) with a `WindowProc` callback
  - A message pump (`GetMessage`/`DispatchMessage` loop)
  - Window class registration via `RegisterClassEx`
  - All via ctypes — complex but doable

**Complexity analysis:**
- Need to create hidden window: `CreateWindowEx` with `HWND_MESSAGE` parent
- Need `WNDCLASSEX` structure, `RegisterClassExW`, `WNDPROC` callback via `ctypes.WINFUNCTYPE`
- Need message pump in dedicated thread
- ~80-100 lines of ctypes boilerplate vs ~20 lines for polling

**Decision: Polling wins.**
| Criterion | Polling | Event-Driven |
|-----------|---------|--------------|
| Implementation complexity | ~20 LOC | ~80-100 LOC |
| Latency | 1s max (acceptable for KVM) | Instant |
| Reliability | High (simple loop) | Medium (message pump edge cases) |
| Fits existing architecture | Yes (already polls every 1s) | No (needs new thread model) |
| Maintenance burden | Low | Medium |

The 1-second polling delay is negligible for KVM switching scenarios (user takes several seconds to move between PCs). Event-driven adds complexity without meaningful UX benefit.

---

## 3. Implementation Plan

### 3.1 Files to Modify
| File | Changes |
|------|---------|
| `like-move/like_move/config.py` | Add `TriggerMode` enum, extend `JigglerState` with `trigger_mode` and `monitor_devices` |
| `like-move/like_move/jiggler.py` | Update `MonitorThread._check_and_jiggle()` to branch on `trigger_mode` |
| `like-move/like_move/tray.py` | Add "Modo" submenu (radio) and "Dispositivos KVM" submenu (checkable) |

### 3.2 Files to Create
| File | Purpose |
|------|---------|
| `like-move/like_move/device_monitor.py` | Device detection: monitor count via `GetSystemMetrics`, mouse/keyboard count via `GetRawInputDeviceList` |

### 3.3 Files NOT to Modify
| File | Reason |
|------|--------|
| `like-move/like_move/detector.py` | Existing functions (`get_idle_time_ms`, `is_screen_locked`) stay intact |
| `like-move/main.pyw` | Entry point unchanged |
| `like-move/requirements.txt` | No new dependencies (ctypes is stdlib) |

### 3.4 No New Dependencies
All new APIs are in `User32.dll`, already used via ctypes. No pip packages needed.

---

## 4. Detailed Implementation Steps

### Step 1: `config.py` — Add TriggerMode enum and extend JigglerState

**Add:**
- `TriggerMode(enum.Enum)` with values: `IDLE`, `KVM`, `BOTH`, `ALWAYS`
- `JigglerState.trigger_mode: TriggerMode = TriggerMode.IDLE`
- `JigglerState.monitor_devices: set[str] = {"monitor"}` (valid: "monitor", "mouse", "keyboard")

**Backward compatibility:** Default mode `IDLE` preserves current behavior exactly.

### Step 2: `device_monitor.py` — New module for device detection

**Functions to implement:**

```
get_monitor_count() -> int
    Calls user32.GetSystemMetrics(SM_CMONITORS)
    Returns number of active display monitors

get_input_device_counts() -> dict[str, int]
    Calls user32.GetRawInputDeviceList
    Returns {"mouse": N, "keyboard": M}

DeviceBaseline (class):
    Stores initial device counts on creation
    has_disconnection(monitor_devices: set[str]) -> bool
        Compares current counts to baseline
        Returns True if any monitored device count dropped
    refresh() -> None
        Updates baseline to current counts (called on reconnection)
```

**Design rationale for `DeviceBaseline`:**
- On first check (or when transitioning to KVM mode), capture device counts as baseline
- Subsequent polls compare against baseline
- If count drops → device disconnected → trigger jiggle
- When counts restore to >= baseline → reconnected → refresh baseline, stop jiggling
- Handles multiple monitors/mice/keyboards correctly

**ctypes declarations needed:**
- `user32.GetSystemMetrics.argtypes = [ctypes.c_int]`
- `user32.GetSystemMetrics.restype = ctypes.c_int`
- `user32.GetRawInputDeviceList.argtypes = [POINTER(RAWINPUTDEVICELIST), POINTER(c_uint), c_uint]`
- `user32.GetRawInputDeviceList.restype = c_uint`
- `RAWINPUTDEVICELIST` structure (HANDLE + DWORD)

### Step 3: `jiggler.py` — Update MonitorThread logic

**Changes to `MonitorThread.__init__`:**
- Add `self._device_baseline: Optional[DeviceBaseline] = None`

**Changes to `_check_and_jiggle`:**
```
if not enabled: return
if is_screen_locked(): return

should_jiggle = False

if trigger_mode in (IDLE, BOTH):
    if idle_ms >= threshold * 1000:
        should_jiggle = True

if trigger_mode in (KVM, BOTH):
    if device_baseline is None:
        device_baseline = DeviceBaseline()  # capture initial counts
    if device_baseline.has_disconnection(state.monitor_devices):
        should_jiggle = True
    else:
        device_baseline.refresh()  # counts restored, update baseline

if trigger_mode == ALWAYS:
    should_jiggle = True

if should_jiggle:
    # respect jiggle_interval
    if elapsed >= jiggle_interval:
        jiggle_mouse()
```

**Important:** When `trigger_mode` changes at runtime (via tray menu), reset `_device_baseline` to None so it recaptures on next KVM check.

### Step 4: `tray.py` — Add mode and device submenus

**New menu structure:**
```
✓ Ativo
─────────
  Modo ►
    ○ Inatividade    (TriggerMode.IDLE)
    ○ KVM            (TriggerMode.KVM)
    ○ Ambos          (TriggerMode.BOTH)
    ○ Sempre         (TriggerMode.ALWAYS)
  Dispositivos KVM ► (visible only when mode includes KVM)
    ☑ Monitor
    ☐ Mouse
    ☐ Teclado
  Threshold ►
    ○ 15s
    ○ 30s  ← selected
    ○ 60s
    ○ 2min
    ○ 5min
─────────
  Sair
```

**pystray visibility consideration:**
- pystray `MenuItem` supports `visible` parameter with a callable
- For "Dispositivos KVM": `visible=lambda item: state.trigger_mode in (KVM, BOTH)`
- For "Threshold": `visible=lambda item: state.trigger_mode in (IDLE, BOTH)` — threshold is relevant only when idle detection is active
- Actually, keep Threshold always visible — it's still useful context even in KVM mode, and simplifies the UI

**Callbacks:**
- `_on_set_mode(mode)` → sets `state.trigger_mode`, resets device baseline in MonitorThread
- `_on_toggle_device(device_name)` → toggles device in `state.monitor_devices` set
- `_is_device_checked(device_name)` → checks if device is in set

**Communication between TrayApp and MonitorThread for baseline reset:**
- Add `MonitorThread.reset_device_baseline()` method that sets `_device_baseline = None`
- TrayApp calls it when trigger_mode changes
- Thread-safe: `_device_baseline` is only written from one thread at a time (tray sets None, monitor thread creates new one)

---

## 5. Risks and Mitigations

### 5.1 RISK: GetRawInputDeviceList may include virtual/phantom devices
- **Severity:** Medium
- **Scenario:** Windows may report virtual HID devices (e.g., Bluetooth radio, USB hub) that inflate counts unpredictably
- **Mitigation:** Filter strictly by `dwType == RIM_TYPEMOUSE` (0) and `dwType == RIM_TYPEKEYBOARD` (1). These are specific to actual mouse/keyboard devices, not generic HIDs.
- **Additional mitigation:** Use relative comparison (count *dropped*), not absolute values. If a phantom device appears/disappears, the baseline auto-adjusts via `refresh()`.

### 5.2 RISK: KVM switch may not fully disconnect USB devices
- **Severity:** Low-Medium
- **Scenario:** Some KVM switches use USB hub emulation — the OS sees devices as "still connected" even when switched away
- **Mitigation:** Monitor detection (via SM_CMONITORS) is more reliable since display signals are clearly lost. Document that mouse/keyboard detection works best with KVM switches that fully disconnect USB.
- **Note:** This is inherent to the hardware, not a software limitation.

### 5.3 RISK: Race condition on `_device_baseline` between tray and monitor thread
- **Severity:** Low
- **Scenario:** Tray sets `_device_baseline = None` while monitor thread is reading it
- **Mitigation:** Python's GIL makes `None` assignment atomic. Monitor thread checks `if baseline is None` before using it. Worst case: one extra polling cycle before baseline is recaptured.

### 5.4 RISK: `GetRawInputDeviceList` two-phase call TOCTOU
- **Severity:** Low
- **Scenario:** Device count changes between the NULL call (get count) and the fill call
- **Mitigation:** Use the retry loop pattern from Microsoft's documentation — if `ERROR_INSUFFICIENT_BUFFER`, reallocate and retry.

### 5.5 RISK: pystray menu rebuild needed for dynamic visibility
- **Severity:** Low
- **Scenario:** pystray's `visible` callable for "Dispositivos KVM" might not update dynamically on all platforms
- **Mitigation:** pystray on Windows evaluates `visible` callable each time menu is opened. Tested behavior — works correctly.

### 5.6 RISK: ALWAYS mode could interfere with normal mouse usage
- **Severity:** Low
- **Scenario:** Continuous jiggle (+1px/-1px every 10s) while user is actively using mouse
- **Mitigation:** Movement is 1px and round-trips instantly — imperceptible. Still respects `jiggle_interval`. Still skips when screen is locked.

---

## 6. Implementation Order (Dependencies)

```
Step 1: config.py (TriggerMode enum + JigglerState fields)
   ↓
Step 2: device_monitor.py (new module, depends on nothing except ctypes)
   ↓
Step 3: jiggler.py (depends on config.py changes + device_monitor.py)
   ↓
Step 4: tray.py (depends on config.py changes + jiggler.py changes)
```

All steps are sequential — each depends on the previous.

---

## 7. Testing Strategy

- **Manual testing (KVM mode):** Change display count in Windows Display Settings (disable a monitor) → verify jiggle triggers
- **Manual testing (mouse/keyboard):** Unplug USB mouse → verify device count drops → jiggle triggers. Replug → jiggle stops.
- **Regression:** Verify IDLE mode works exactly as before (default)
- **ALWAYS mode:** Toggle on → verify jiggle every `jiggle_interval` regardless of idle
- **Screen lock:** All modes should skip jiggle when screen is locked

---

## 8. Summary of Win32 API Calls (All ctypes, No pywin32, No Admin)

| API | DLL | Purpose | Complexity |
|-----|-----|---------|------------|
| `GetSystemMetrics(SM_CMONITORS)` | User32 | Count monitors | Trivial |
| `GetRawInputDeviceList` | User32 | List HID devices | Medium (two-phase + struct) |
| `GetLastInputInfo` | User32 | Idle time (existing) | Already implemented |
| `OpenInputDesktop` | User32 | Screen lock (existing) | Already implemented |
| `SendInput` | User32 | Mouse jiggle (existing) | Already implemented |
