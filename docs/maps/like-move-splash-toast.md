# Task Map: like-move-splash-toast

## Intent
Adicionar splash screen com animação de fade e toast notification do Windows ao iniciar o app like-move, para dar feedback visual ao usuário de que o app está carregando e rodando.

## Decision Log

| # | Decisão | Justificativa |
|---|---------|---------------|
| 1 | Splash via Win32 layered window (WS_EX_LAYERED + UpdateLayeredWindow) | Zero dependências novas — usa ctypes (stdlib) + Pillow (já existente). Per-pixel alpha para cantos arredondados. |
| 2 | Toast via `pystray.Icon.notify()` | API nativa do pystray já disponível — evita dependência de winotify ou Shell_NotifyIconW manual. |
| 3 | Fade-in → hold → fade-out (~2.5s total) | Rápido o suficiente para não irritar, lento o suficiente para ser percebido. 16 steps × 25ms per fade (~400ms cada), 1.5s hold. |
| 4 | Splash antes do tray (blocking em main.pyw) | Splash aparece imediatamente, tray carrega depois. Sequência natural de startup. |
| 5 | Fail-silent no splash (try/except no show_splash) | App DEVE iniciar mesmo se splash falhar — funcionalidade é cosmética. |

## Files Changed

| Arquivo | Mudança |
|---------|---------|
| `like-move/like_move/splash.py` | **NOVO** — Módulo completo de splash screen (343 lines). Win32 layered window, WNDPROC, BITMAPINFO, pre-multiplied alpha, fade animation. Renderiza com Pillow (ícone + texto "like-move" + versão + "Iniciando…"). |
| `like-move/main.pyw` | Adicionado `from like_move.splash import show_splash` + chamada `show_splash()` antes de `TrayApp()`. |
| `like-move/like_move/tray.py` | Adicionado `icon.notify("like-move está rodando — clique direito para configurar", "like-move")` no `_setup()` callback. |

## Architecture Notes

- **Splash usa mesmo padrão Win32 do device_monitor.py**: WNDCLASSEXW, WNDPROC via ctypes.WINFUNCTYPE, RegisterClassExW/CreateWindowExW.
- **Pre-multiplied alpha**: Necessário para UpdateLayeredWindow — Pillow gera RGBA normal, conversão manual no `_pil_to_hbitmap()`.
- **Asset resolution**: `_asset_path()` resolve tanto dev (`os.path.dirname`) quanto PyInstaller (`sys._MEIPASS`).
- **Cleanup completo**: DeleteObject(hbmp), DeleteDC, ReleaseDC, DestroyWindow, UnregisterClassW — sem resource leaks.
- **Toast**: `pystray.Icon.notify()` usa Shell_NotifyIconW internamente — aparece como balloon tip / Action Center notification.

## Pipeline Summary

| Step | Agent | Duração | Resultado |
|------|-------|---------|-----------|
| 1 | Researcher | ~4min | Mapeou toda a estrutura do projeto (14 arquivos), pesquisou abordagens (Win32 layered, tkinter, winotify, pystray.notify). Recomendou Win32 + pystray. |
| 2 | Implementor | ~5min | Criou `splash.py`, editou `main.pyw` e `tray.py`, commitou. |
| 3 | Validator | ~3min | Verificou implementação, validou estrutura dos arquivos. |

## Risks & Mitigations

- **PyInstaller spec**: `splash.py` não precisa de hidden imports extras (usa ctypes + Pillow já incluídos). Spec sem alteração.
- **Segoe UI font**: Fallback para `ImageFont.load_default()` se não encontrar — funciona em qualquer Windows.
- **Blocking splash**: 2.5s de delay no startup é aceitável. Se precisar reduzir, ajustar `fade_steps` e `fade_delay`.
