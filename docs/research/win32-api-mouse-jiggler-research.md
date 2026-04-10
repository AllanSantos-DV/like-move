# Research: Win32 APIs & Libraries for like-move (Mouse Jiggler)

**Date:** 2026-04-10
**Topic:** Win32 API research for Python mouse jiggler using ctypes

---

## 1. Win32 APIs Researched

### 1.1 `user32.GetLastInputInfo`
- **Source:** https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getlastinputinfo
- **Purpose:** Retrieves the time of the last input event (keyboard, mouse, etc.)
- **DLL:** User32.dll
- **Min OS:** Windows 2000 Professional
- **Signature:** `BOOL GetLastInputInfo([out] PLASTINPUTINFO plii)`
- **Returns:** Nonzero on success, zero on failure
- **Key details:**
  - Takes a pointer to `LASTINPUTINFO` struct
  - Provides **session-specific** user input info (not system-wide)
  - Tick count is NOT guaranteed to be incremental (timing gaps possible)
  - No admin required — user-space API

### 1.2 `LASTINPUTINFO` Structure
- **Source:** https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-lastinputinfo
- **Fields:**
  - `cbSize` (UINT): Must be set to `sizeof(LASTINPUTINFO)` = 8 bytes
  - `dwTime` (DWORD): Tick count when last input event was received
- **ctypes mapping:**
  ```
  Structure with fields:
    cbSize: c_uint (set to 8)
    dwTime: c_ulong
  ```

### 1.3 `kernel32.GetTickCount`
- **Source:** https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-gettickcount
- **Purpose:** Milliseconds elapsed since system start
- **DLL:** Kernel32.dll
- **Returns:** DWORD (wraps at 49.7 days)
- **Resolution:** 10-16 ms (system timer resolution)
- **⚠️ RISK: Overflow after 49.7 days of continuous uptime**
- **Mitigation:** Use `GetTickCount64` (available since Vista/Server 2008) which returns ULONGLONG, no overflow risk
- **Idle time calculation:** `idle_ms = GetTickCount() - lastInputInfo.dwTime`

### 1.4 `user32.OpenInputDesktop` (via `OpenInputDesktopW`)
- **Source:** https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-openinputdesktop
- **Purpose:** Opens the desktop that receives user input
- **DLL:** User32.dll
- **Signature:** `HDESK OpenInputDesktop(DWORD dwFlags, BOOL fInherit, ACCESS_MASK dwDesiredAccess)`
- **Returns:** Handle to desktop on success, **NULL on failure (screen locked)**
- **Lock detection logic:**
  - Call `OpenInputDesktop(0, False, 0)` — request minimal access
  - If returns NULL → screen is locked (Winlogon/Secure Desktop active)
  - If returns non-NULL → screen is unlocked, must call `CloseDesktop(handle)`
- **No admin required** — user-space API

### 1.5 `user32.CloseDesktop`
- **Source:** https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-closedesktop
- **Purpose:** Closes an open desktop handle
- **DLL:** User32.dll
- **Signature:** `BOOL CloseDesktop(HDESK hDesktop)`
- **⚠️ Must always close handles returned by OpenInputDesktop to avoid handle leaks**

### 1.6 `user32.GetCursorPos`
- **Source:** https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getcursorpos
- **Purpose:** Retrieves current cursor screen coordinates
- **DLL:** User32.dll
- **Signature:** `BOOL GetCursorPos([out] LPPOINT lpPoint)`
- **Returns:** Screen coordinates via POINT struct (x, y as LONG)
- **Requires:** WINSTA_READATTRIBUTES access (standard user has this)

### 1.7 `user32.SetCursorPos`
- **Source:** https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setcursorpos
- **Purpose:** Moves cursor to specified screen coordinates
- **DLL:** User32.dll
- **Signature:** `BOOL SetCursorPos(int X, int Y)`
- **⚠️ CRITICAL FINDING:** SetCursorPos directly modifies cursor position and generates WM_MOUSEMOVE messages. It does reset the Windows idle timer in practice. However, it's less reliable than SendInput for some edge cases.

### 1.8 `user32.SendInput` (RECOMMENDED for jiggle)
- **Source:** https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput
- **Purpose:** Synthesizes keystrokes, mouse motions, and button clicks
- **DLL:** User32.dll
- **Signature:** `UINT SendInput(UINT cInputs, LPINPUT pInputs, int cbSize)`
- **Returns:** Number of events successfully inserted
- **Subject to UIPI** — can only inject into equal or lesser integrity level apps (not an issue for user-space mouse jiggle)
- **Why preferred over SetCursorPos:**
  - Injects directly into the input stream (the OS input queue)
  - Guaranteed to reset the system idle timer
  - Used by professional mouse jiggler tools
  - Can do relative movement (no need to read current position first)
- **INPUT structure for mouse movement:**
  ```
  INPUT.type = INPUT_MOUSE (0)
  INPUT.mi.dx = 1  (relative pixels)
  INPUT.mi.dy = 0
  INPUT.mi.dwFlags = MOUSEEVENTF_MOVE (0x0001)
  ```

### 1.9 `user32.mouse_event` (DEPRECATED alternative)
- **Source:** https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-mouse_event
- **Purpose:** Synthesizes mouse motion and button clicks
- **Status:** **Deprecated — use SendInput instead**
- **Simpler via ctypes** but not recommended for new code
- **Flags:** MOUSEEVENTF_MOVE (0x0001), MOUSEEVENTF_ABSOLUTE (0x8000)

---

## 2. Library Research

### 2.1 pystray
- **Source:** https://pypi.org/project/pystray/
- **Latest version:** 0.19.5 (2023-09-17)
- **License:** LGPL-3.0+
- **Windows backend:** `win32` — all features supported
- **Admin required:** NO — runs in user-space
- **Key findings:**
  - `Icon.run()` is blocking — designed for main thread
  - On **Windows specifically**, `run()` CAN be called from non-main thread (unique to Windows)
  - `setup` callback runs in separate thread when icon is ready
  - `Icon.stop()` terminates the run loop
  - `Menu` with `MenuItem` supports: text, action callback, checkable items, submenus
  - `run_detached()` available for framework integration
  - Supports notifications on Windows
  - Automatically restores icon after explorer.exe crash
- **Menu creation pattern:**
  ```python
  from pystray import Icon, Menu, MenuItem
  icon = Icon('name', image, menu=Menu(
      MenuItem('Text', callback),
      MenuItem('Checkable', callback, checked=lambda item: state),
      MenuItem('Quit', lambda: icon.stop())
  ))
  icon.run()
  ```

### 2.2 Pillow (PIL)
- **Purpose:** Generate tray icon image programmatically
- **No admin required** for `pip install --user`
- **Usage:** Create 64x64 image with `Image.new()` and `ImageDraw.Draw()`
- **Required by pystray** for icon display

---

## 3. Critical Findings & Risks

### 3.1 ⚠️ SetCursorPos vs SendInput for Idle Timer Reset
- **Risk Level:** HIGH
- **Finding:** `SetCursorPos` works in most cases but `SendInput` is the reliable choice
- **Recommendation:** Use `SendInput` with `INPUT_MOUSE` + `MOUSEEVENTF_MOVE` for relative movement
- **Advantage:** SendInput with relative movement (+1px, then -1px) doesn't need to read cursor position first

### 3.2 ⚠️ GetTickCount Overflow
- **Risk Level:** MEDIUM (49.7 days uptime)
- **Recommendation:** Use `GetTickCount64` (Kernel32.dll, Vista+) to avoid wrap-around
- **Idle calc:** `idle_ms = GetTickCount64() - lastInputInfo.dwTime`
- **Note:** LASTINPUTINFO.dwTime is still DWORD (32-bit), but the subtraction handles the wrap if both values overflow consistently

### 3.3 ⚠️ Handle Leak from OpenInputDesktop
- **Risk Level:** MEDIUM
- **Finding:** Every successful `OpenInputDesktop()` call returns a handle that MUST be closed with `CloseDesktop()`
- **Recommendation:** Always use try/finally pattern when calling OpenInputDesktop

### 3.4 ⚠️ UIPI (User Interface Privilege Isolation)
- **Risk Level:** LOW
- **Finding:** `SendInput` is subject to UIPI — cannot inject into higher integrity processes
- **Impact:** Not relevant for mouse jiggle since we're just moving the cursor, not targeting specific apps
- **Confirmation:** User-space mouse movement works fine without admin

### 3.5 ⚠️ pystray Threading Model
- **Risk Level:** LOW (Windows only)
- **Finding:** On Windows, `pystray.Icon.run()` can be called from non-main thread
- **Recommendation:** Run pystray in main thread, monitor loop in daemon thread (setup callback)

### 3.6 ✅ No Admin Required — Confirmed
All APIs used are in User32.dll/Kernel32.dll and require only standard user privileges:
- `GetLastInputInfo` — user-space
- `OpenInputDesktop` — user-space (returns NULL on locked screen, no elevated access needed)
- `GetCursorPos` / `SetCursorPos` — WINSTA_READATTRIBUTES / WINSTA_WRITEATTRIBUTES (standard user)
- `SendInput` — user-space (UIPI only blocks injection into HIGHER integrity)
- `GetTickCount` / `GetTickCount64` — user-space

---

## 4. ctypes Implementation Notes

### 4.1 Structures Needed
```
LASTINPUTINFO:
  cbSize: c_uint = 8
  dwTime: c_ulong

POINT:
  x: c_long
  y: c_long

MOUSEINPUT:
  dx: c_long
  dy: c_long
  mouseData: c_ulong
  dwFlags: c_ulong
  time: c_ulong
  dwExtraInfo: POINTER(c_ulong) or c_void_p

INPUT:
  type: c_ulong  (INPUT_MOUSE = 0)
  union: MOUSEINPUT | KEYBDINPUT | HARDWAREINPUT
```

### 4.2 Function Prototypes (ctypes)
```
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.GetLastInputInfo(ctypes.POINTER(LASTINPUTINFO)) -> BOOL
user32.OpenInputDesktopW(DWORD, BOOL, DWORD) -> HDESK (c_void_p)
user32.CloseDesktop(c_void_p) -> BOOL
user32.GetCursorPos(ctypes.POINTER(POINT)) -> BOOL
user32.SetCursorPos(c_int, c_int) -> BOOL
user32.SendInput(c_uint, ctypes.POINTER(INPUT), c_int) -> c_uint
kernel32.GetTickCount() -> DWORD
kernel32.GetTickCount64() -> c_ulonglong  (Vista+)
```

### 4.3 Jiggle Strategy (Recommended)
```
# Move mouse +1px relative, then -1px relative
# Using SendInput with MOUSEEVENTF_MOVE (relative mode)
# Two calls in sequence: (+1, 0) then (-1, 0)
# Net movement: zero — cursor returns to original position
# Total time: < 1ms
```

---

## 5. Architecture Decisions

### 5.1 Threading Model
- **Main thread:** pystray Icon.run() (blocking event loop)
- **Daemon thread:** Monitor loop (started via setup callback)
  - Checks idle time every ~1 second
  - If idle > threshold AND screen not locked → jiggle
  - If screen locked → skip (save CPU)
  - Respects enabled/disabled state from tray menu

### 5.2 Jiggle Approach Decision
| Approach | Pros | Cons | Recommendation |
|----------|------|------|----------------|
| SetCursorPos | Simple, well-tested | Needs GetCursorPos first, may not reset timer in edge cases | ❌ |
| mouse_event | Simple ctypes call | Deprecated by Microsoft | ❌ |
| SendInput | Official recommendation, reliable timer reset, relative movement | More complex struct setup | ✅ **Use this** |

### 5.3 Configuration Defaults
- `IDLE_THRESHOLD_SECONDS`: 30 (start jiggling after 30s idle)
- `JIGGLE_INTERVAL_SECONDS`: 10 (jiggle every 10s while idle)
- `CHECK_INTERVAL_SECONDS`: 1 (check idle status every 1s)
- `JIGGLE_PIXELS`: 1 (move 1px right then 1px left)
