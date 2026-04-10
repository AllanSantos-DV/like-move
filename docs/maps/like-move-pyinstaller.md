# Task Map: like-move-pyinstaller

## Intent
Empacotar like-move como .exe standalone via PyInstaller para distribuição sem dependência de Python instalado.

## Decisões de Design
| Decisão | Alternativas | Escolha | Motivo |
|---------|-------------|---------|--------|
| Empacotador | PyInstaller vs cx_Freeze vs Nuitka | PyInstaller | Mais maduro, melhor suporte a pystray/Pillow, onefile mode |
| Modo | --onefile vs --onedir | --onefile | Um único .exe para distribuir, sem pasta de suporte |
| Console | --console vs --noconsole | --noconsole (windowed) | App de tray, sem janela de console |
| Invocação | pyinstaller CLI vs python -m PyInstaller | python -m PyInstaller | Compatível com --user installs onde CLI não está no PATH |
| Ícone | .ico estático vs gerado por script | Gerado por script (generate_icon.py) | Reutiliza mesma lógica do tray.py, multi-resolução |

## Arquivos Criados
| Arquivo | Propósito |
|---------|-----------|
| `like-move/like-move.spec` | Spec file PyInstaller (onefile, windowed, hidden imports, ícone) |
| `like-move/build.ps1` | Script PowerShell de build automatizado |
| `like-move/generate_icon.py` | Gera like-move.ico com múltiplas resoluções (16/32/48/256) |
| `like-move/assets/like-move.ico` | Ícone do .exe (gerado pelo script) |

## Arquivos Modificados
| Arquivo | Mudança |
|---------|---------|
| `like-move/.gitignore` | Adicionado build/, dist/ |
| `like-move/README.md` | Adicionada seção Build com instruções |

## Resultado do Build
- **Output**: `like-move/dist/like-move.exe`
- **Tamanho**: ~25.55 MB (Python + deps embarcados)
- **Validação**: compile + lint limpos (flake8 + ruff)

## Hidden Imports Identificados
- pystray backends Windows (pystray._util.win32)
- Pillow image plugins (PIL.*)
- ctypes.wintypes (já incluído automaticamente)

## Pipeline
- **Template**: research-first (3 steps)
- **Step 1** (researcher, 3min): Pesquisou hooks PyInstaller pra pystray/Pillow, hidden imports
- **Step 2** (implementor, 3min): Criou spec/build script/icon, testou build (25.55MB OK)
- **Step 3** (validator, 1min): Compile + lint limpos, sem correções
- **Duração total**: ~7 min
- **Worktree isolado**: não (artefatos de build precisam ficar acessíveis)

## Uso
```powershell
cd like-move
.\build.ps1           # Gera dist/like-move.exe
.\dist\like-move.exe  # Roda standalone
```
