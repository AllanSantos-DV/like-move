# Task Map: like-move-config-modes

## Intent
Adicionar modos de detecção configuráveis ao like-move: trigger por inatividade, KVM (desconexão de dispositivos), ambos, ou always-on. Com seleção de dispositivos a monitorar (monitor, mouse, teclado).

## Contexto
- Projeto: like-move (mouse jiggler inteligente para Windows)
- Antes: apenas modo inatividade (idle > threshold → jiggle)
- Usuário quer configurar via menu do tray qual trigger usar

## Decisões de Design
| Decisão | Alternativas | Escolha | Motivo |
|---------|-------------|---------|--------|
| Device detection | WM_DEVICECHANGE (event-driven) vs Polling | Polling a cada 1s | ~80 LOC menos, sem hidden window, suficiente para KVM |
| Contagem de monitores | EnumDisplayMonitors vs GetSystemMetrics(SM_CMONITORS) | GetSystemMetrics | Mais simples, sem callback/struct |
| Contagem mouse/teclado | RegisterDeviceNotification vs GetRawInputDeviceList | GetRawInputDeviceList | User-space, sem admin, polling simples |
| Trigger modes | 3 modos vs 4 modos | 4 modos (IDLE, KVM, BOTH, ALWAYS) | ALWAYS para uso sem trigger automático |

## Módulos Afetados
| Arquivo | Mudança |
|---------|---------|
| `like-move/like_move/config.py` | Adicionado enum `TriggerMode`, campos `trigger_mode` e `monitor_devices` no `JigglerState` |
| `like-move/like_move/device_monitor.py` | **NOVO** — polling de monitores (SM_CMONITORS), mouse/teclado (GetRawInputDeviceList), classe `DeviceMonitor` |
| `like-move/like_move/jiggler.py` | `MonitorThread._check_and_jiggle()` atualizado para considerar `trigger_mode` |
| `like-move/like_move/tray.py` | Novos submenus: Modo (radio: Inatividade/KVM/Ambos/Sempre), Dispositivos KVM (checkable: Monitor/Mouse/Teclado) |
| `like-move/like_move/detector.py` | NÃO alterado (preservado) |

## Riscos Mapeados
- GetRawInputDeviceList pode contar dispositivos virtuais (RDP, VMware) — mitigado com baseline na inicialização
- SM_CMONITORS retorna 0 se nenhum monitor físico conectado — tratado no polling
- Polling 1s consome CPU mínimo mas mais que event-driven — aceitável para o caso
- Lint: 1 erro de linha longa corrigido pelo validator

## Pipeline
- **Template**: research-first (3 steps)
- **Step 1** (researcher): Pesquisou APIs Win32, decidiu polling, documentou em docs/research/
- **Step 2** (implementor): Criou device_monitor.py, atualizou config/jiggler/tray
- **Step 3** (validator): Compile OK, lint corrigido (1 erro linha longa)
- **Duração total**: ~6 min
- **Lessons captured**: 2 (polling vs event-driven, SM_CMONITORS vs EnumDisplayMonitors)

## Próximos Passos Possíveis
- Persistir configurações em arquivo JSON (atualmente só em memória)
- Auto-start com Windows (atalho na pasta Startup)
- Empacotar como .exe com PyInstaller
