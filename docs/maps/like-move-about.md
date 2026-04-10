# Task Map: like-move-about

## Intent
Adicionar item "Sobre" no menu do tray com instruções básicas de uso do app.

## Arquivo Modificado
- `like-move/like_move/tray.py` — método `_on_about()` com MessageBoxW + item "Sobre" no menu

## Pipeline
- **Template**: quick-fix (2 steps)
- **Step 1** (implementor, 38s): Adicionou método + menu item
- **Step 2** (validator): Compile + lint OK
- **Auto-merge**: sim
