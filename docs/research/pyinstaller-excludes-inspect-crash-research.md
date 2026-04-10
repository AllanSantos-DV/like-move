# Research: PyInstaller Excludes — `inspect` Module Crash

**Date:** 2026-04-10
**Context:** `like-move.exe` crashes on startup with `ImportError: No module named 'inspect'`

---

## 1. Bug Analysis

### Error Message
```
ImportError: this platform is not supported: No module named 'inspect'
```

### Root Cause
The `like-move.spec` file (line 51) includes `'inspect'` in the `excludes` list passed to `Analysis()`. This prevents PyInstaller from bundling the `inspect` standard library module into the executable.

### Why It Crashes
The import chain is:
1. `main.pyw` → `from like_move.tray import TrayApp`
2. `tray.py` → `from pystray import Icon, Menu, MenuItem`
3. `pystray/__init__.py` → calls `backend()` which loads `pystray._win32`
4. `pystray/_win32.py` → `from . import _base`
5. **`pystray/_base.py`** → **`import inspect`** ← FAILS HERE

The `inspect` module is used in `_base.py`'s `MenuItem._assert_action()` method:
```python
argcount = action.__code__.co_argcount - (
    1 if inspect.ismethod(action) else 0)
```

This is called every time a `MenuItem` is constructed, making it a critical runtime dependency for any pystray app that uses menus (which like-move does).

---

## 2. PyInstaller Documentation Findings

### Source: [pyinstaller.org/en/stable/spec-files.html](https://pyinstaller.org/en/stable/spec-files.html)

The `excludes` parameter in `Analysis()` tells PyInstaller to **completely prevent** the named modules from being bundled. There is no built-in safety check — if a module in `excludes` is actually needed at runtime, the app will crash with `ImportError`.

### Source: [pyinstaller.org/en/stable/when-things-go-wrong.html](https://pyinstaller.org/en/stable/when-things-go-wrong.html)

Key guidance:
- Build-time warnings about missing modules go to `build/_name_/warn-_name_.txt`
- When app terminates with `ImportError`, examine the warning file
- Use `--debug=imports` flag to trace imports and find which modules are needed
- Hidden imports (via `__import__()`, `importlib.import_module()`, etc.) may not be detected by Analysis

### Implication
PyInstaller does NOT warn when an `excludes` entry conflicts with a transitive dependency. The developer is responsible for ensuring excluded modules aren't needed.

---

## 3. pystray Source Code Analysis

### Files Examined
- `pystray/__init__.py` — backend selection, imports `_base.Menu`, `_base.MenuItem`
- `pystray/_base.py` — base Icon/Menu/MenuItem classes
- `pystray/_win32.py` — Windows backend
- `pystray/_util/__init__.py` — utility functions

### pystray's Standard Library Dependencies

| Module | Used In | Purpose | Can Exclude? |
|--------|---------|---------|--------------|
| `functools` | `_base.py` | `@functools.wraps` in callbacks | ❌ NO |
| **`inspect`** | **`_base.py`** | **`inspect.ismethod()` in MenuItem** | **❌ NO** |
| `itertools` | `_base.py` | `itertools.dropwhile` in Menu filtering | ❌ NO |
| `logging` | `_base.py` | Logger for icon events | ❌ NO |
| `queue` | `_base.py`, `_win32.py` | Thread-safe queue for events | ❌ NO |
| `threading` | `_base.py`, `_win32.py` | Setup thread, event loop | ❌ NO |
| `ctypes` | `_win32.py` | Win32 API bindings | ❌ NO |
| `contextlib` | `_util/__init__.py` | Context manager for temp icon files | ❌ NO |
| `os` | `_util/__init__.py`, `__init__.py` | File operations, env vars | ❌ NO |
| `tempfile` | `_util/__init__.py` | Temp file for serialized icon | ❌ NO |
| `sys` | `__init__.py`, `_win32.py` | Platform detection | ❌ NO |

---

## 4. Safety Analysis of All Current Excludes

### Current `excludes` list in `like-move.spec`:
```python
excludes=[
    'tkinter', '_tkinter', 'unittest', 'email', 'html', 'http',
    'xml', 'pydoc', 'doctest', 'argparse', 'difflib',
    'inspect',           # ← BUG
    'multiprocessing', 'socketserver',
]
```

### Exclude-by-Exclude Analysis

| Module | Used by Project? | Used by pystray? | Used by Pillow? | Verdict |
|--------|-----------------|-------------------|-----------------|---------|
| `tkinter` | ❌ | ❌ | ❌ (optional viewer) | ✅ SAFE |
| `_tkinter` | ❌ | ❌ | ❌ | ✅ SAFE |
| `unittest` | ❌ | ❌ | ❌ | ✅ SAFE |
| `email` | ❌ | ❌ | ❌ | ✅ SAFE |
| `html` | ❌ | ❌ | ❌ | ✅ SAFE |
| `http` | ❌ | ❌ | ❌ | ✅ SAFE |
| `xml` | ❌ | ❌ | ❌ (optional XML metadata) | ✅ SAFE |
| `pydoc` | ❌ | ❌ | ❌ | ✅ SAFE |
| `doctest` | ❌ | ❌ | ❌ | ✅ SAFE |
| `argparse` | ❌ | ❌ | ❌ | ✅ SAFE |
| `difflib` | ❌ | ❌ | ❌ | ✅ SAFE |
| **`inspect`** | **❌** | **✅ `_base.py`** | **❌** | **❌ NOT SAFE** |
| `multiprocessing` | ❌ | ❌ | ❌ | ✅ SAFE |
| `socketserver` | ❌ | ❌ | ❌ | ✅ SAFE |

### Evidence for each "SAFE" verdict:
- **`tkinter`/`_tkinter`**: Pillow optionally uses tkinter for `Image.show()` but like-move never calls it. pystray uses native Win32 API, not tkinter.
- **`unittest`/`doctest`**: Test frameworks; never imported at runtime by pystray or Pillow.
- **`email`/`html`/`http`/`xml`**: Network/markup modules. pystray is a local tray app with no network or markup needs. Pillow's core image operations don't require these.
- **`pydoc`**: Documentation generator, never used at runtime.
- **`argparse`**: CLI argument parser. like-move is a GUI app with no CLI arguments. Neither pystray nor Pillow core imports it.
- **`difflib`**: Text diffing library. No text comparison in this app.
- **`multiprocessing`**: like-move uses `threading`, not `multiprocessing`. pystray also uses `threading`.
- **`socketserver`**: Network server framework. No servers in this app.

---

## 5. The `inspect` Module — What It Provides

The `inspect` module itself imports: `dis`, `linecache`, `tokenize`, `token`, `types`, `collections.abc`, `enum`, `importlib`, `ast`, `os`, `re`, `sys`.

None of these are in the `excludes` list, so removing `'inspect'` from excludes is sufficient — its own dependencies will be bundled automatically by PyInstaller.

**Size impact**: The `inspect` module is ~120KB of Python source. Its transitive dependencies are mostly already bundled (e.g., `re`, `os`, `sys`, `enum` are used by the project). Net increase should be minimal (~50-100KB estimated).

---

## 6. Fix Required

### Change
Remove `'inspect'` from the `excludes` list in `like-move/like-move.spec`.

### Before
```python
excludes=[
    'tkinter', '_tkinter', 'unittest', 'email', 'html', 'http',
    'xml', 'pydoc', 'doctest', 'argparse', 'difflib',
    'inspect',
    'multiprocessing', 'socketserver',
],
```

### After
```python
excludes=[
    'tkinter', '_tkinter', 'unittest', 'email', 'html', 'http',
    'xml', 'pydoc', 'doctest', 'argparse', 'difflib',
    'multiprocessing', 'socketserver',
],
```

### Files to Modify
- `like-move/like-move.spec` — Remove `'inspect'` from excludes list (line 51)

### No Other Files Need Changes
The rest of the codebase is correct. The only issue is this single exclude entry.

---

## 7. Verification Steps

1. **Build**: `cd like-move && python -m PyInstaller like-move.spec --noconfirm`
2. **Check build output**: Verify no errors in PyInstaller output
3. **Run exe**: `dist\like-move.exe` — should start without ImportError
4. **Verify tray icon**: Icon should appear in system tray
5. **Check no regression**: Menu should be functional (right-click tray icon)

---

## 8. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Other excludes also break at runtime | Low | High | All verified against pystray/Pillow source |
| `inspect` transitive deps pull in large modules | Low | Low | Most deps already bundled; net size increase ~50-100KB |
| Build fails for unrelated reason | Low | Medium | Check PyInstaller version compatibility |
| Exe size increases significantly | Low | Low | Only `inspect` + `dis`/`tokenize` are new additions |
