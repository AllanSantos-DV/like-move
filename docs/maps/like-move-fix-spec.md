# Task Map: like-move-fix-spec

## Intent
Corrigir crash do like-move.exe — `ImportError: No module named 'inspect'` causado por exclude indevido no PyInstaller spec.

## Bug
- **Sintoma**: `.exe` crasha ao iniciar com `ImportError: No module named 'inspect'`
- **Causa raiz**: `like-move.spec` excluía `'inspect'` na lista de excludes, mas `pystray._base` importa `inspect` em runtime para `MenuItem._assert_action()` → `inspect.ismethod()`
- **Fix**: Remover `'inspect'` da lista de excludes

## Decisões
| Decisão | Escolha | Motivo |
|---------|---------|--------|
| Quais excludes remover | Apenas `inspect` | Pesquisa confirmou que todos os outros (tkinter, unittest, email, etc.) são safe — não são deps de pystray/Pillow/ctypes |
| Impacto no tamanho | ~50-100KB a mais | Aceitável vs crash |

## Arquivo Modificado
- `like-move/like-move.spec` — removido `'inspect'` da lista de excludes

## Validação
- Build passou sem erros
- `.exe` inicia sem crash, tray icon aparece
- Compile + lint limpos

## Pipeline
- **Template**: research-first (3 steps)
- **Step 1** (researcher): Pesquisou doc oficial PyInstaller, analisou imports do pystray, confirmou causa raiz
- **Step 2** (implementor): Editou spec, rebuild, testou .exe — OK
- **Step 3** (validator): Compile + lint limpos
- **Duração total**: ~6 min

## Lição
`pystray._base` usa `inspect.ismethod()` em runtime — nunca excluir `inspect` ao empacotar apps com pystray.
