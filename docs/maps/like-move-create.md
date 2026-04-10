# Task Map: like-move-create

## Intent
Criar projeto Python "like-move" — mouse jiggler inteligente para Windows que previne bloqueio de tela por inatividade quando o usuário alterna entre PCs via KVM switch.

## Contexto
- 2 PCs (desktop + notebook) compartilhando 1 tela/mouse/teclado via KVM switch
- Notebook bloqueia tela por inatividade quando user alterna pro desktop
- Sem acesso admin no notebook

## Decisões de Design
| Decisão | Alternativas | Escolha | Motivo |
|---------|-------------|---------|--------|
| Simulação de input | SetCursorPos vs SendInput | SendInput (MOUSEEVENTF_MOVE) | Mais confiável para resetar idle timer do Windows |
| Timer API | GetTickCount vs GetTickCount64 | GetTickCount64 | Evita overflow de 49.7 dias |
| Win32 binding | pywin32 vs ctypes | ctypes (stdlib) | Sem dependência extra, sem admin pra instalar |
| Tela bloqueada | WTSQuerySessionInformation vs OpenInputDesktop | OpenInputDesktopW | User-space, sem admin |
| Tray icon | tkinter vs pystray | pystray + Pillow | Melhor integração com system tray nativo |
| Entry point | .py vs .pyw | .pyw | Sem janela de console |

## Riscos Mapeados
- **SendInput + UIPI**: Não relevante — jiggle move o cursor do próprio user, sem elevação
- **Handle leak OpenInputDesktop**: Mitigado com try/finally + CloseDesktop
- **GetTickCount DWORD wrap em LASTINPUTINFO**: Subtração entre DWORDs lida corretamente com wrap
- **Antivírus flagging**: Possível — mouse automático pode ser detectado. Mitigação: whitelist manual

## Arquivos Criados
| Arquivo | Propósito |
|---------|-----------|
| `like-move/like_move/__init__.py` | Package marker + version |
| `like-move/like_move/config.py` | Constantes (IDLE_THRESHOLD=30s, JIGGLE_INTERVAL=10s, JIGGLE_PIXELS=1) |
| `like-move/like_move/detector.py` | get_idle_time_ms(), is_screen_locked() via Win32 APIs |
| `like-move/like_move/jiggler.py` | jiggle_mouse() via SendInput, MonitorThread |
| `like-move/like_move/tray.py` | TrayApp com pystray (Enable/Disable, Threshold, Quit) |
| `like-move/main.pyw` | Entry point sem console |
| `like-move/requirements.txt` | pystray>=0.19.0, Pillow>=9.0.0 |
| `like-move/README.md` | Documentação de uso |
| `like-move/.gitignore` | Python gitignore padrão |

## Pipeline
- **Template**: research-first (3 steps)
- **Step 1** (researcher): Pesquisou APIs Win32, pystray, criou plano detalhado
- **Step 2** (implementor): Criou todos os arquivos, ajustou main.pyw pra casar com classes reais
- **Step 3** (validator): Validou syntax, confirmou estado limpo
- **Duração total**: ~8 min
- **Auto-merge**: sim

## Próximos Passos Possíveis
- Testar manualmente no notebook (instalar deps + rodar)
- Adicionar auto-start com Windows (atalho na pasta Startup)
- Empacotar como .exe com PyInstaller (evitar dependência de Python instalado)
