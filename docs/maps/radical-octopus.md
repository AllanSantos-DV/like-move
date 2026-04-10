# Task Map: radical-octopus (About Window Fix)

## Intent
Corrigir janela "Sobre" do like-move: botões OK/fechar não funcionavam (MessageBoxW sem parent, thread do pystray) e visual era o MessageBox padrão do Windows.

## Decision Log

| # | Decisão | Justificativa |
|---|---------|---------------|
| 1 | Módulo separado `about.py` | Mantém tray.py limpo, isola lógica Win32 complexa |
| 2 | Reutiliza helpers do `splash.py` | Importa `_asset_path`, `_pil_to_hbitmap`, `_draw_centered`, structures Win32, DLLs — evita duplicação |
| 3 | Thread dedicada para exibir About | Não bloqueia callbacks do pystray |
| 4 | Janela Win32 layered window | Mesmo padrão do splash — visual consistente com identidade do app |

## Files Changed

| Arquivo | Mudança |
|---------|---------|
| `like-move/like_move/about.py` | **NOVO** — Janela About customizada Win32 com fundo verde, ícone, texto formatado, botão OK funcional |
| `like-move/like_move/tray.py` | `_on_about()` agora importa `about` e roda em thread dedicada em vez de `MessageBoxW` |

## Notes
- `isolateWorktree: false` usado pois a delegação anterior com worktree isolado perdeu as mudanças no cleanup automático
- Precisa rebuild do .exe para testar no PyInstaller
