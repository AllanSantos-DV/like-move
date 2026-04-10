# Task Map: like-move-event-driven

## Intent
Refatorar detecção de dispositivos de polling (1s) para event-driven via WM_DEVICECHANGE, eliminando gasto de CPU quando o notebook está em uso ativo.

## Contexto
- O user reclamou que polling de GetRawInputDeviceList + GetSystemMetrics a cada 1s era desperdício de recursos quando está usando o notebook normalmente
- WM_DEVICECHANGE é broadcast do Windows quando dispositivos conectam/desconectam — custo zero quando não há mudança

## Decisões de Design
| Decisão | Alternativas | Escolha | Motivo |
|---------|-------------|---------|--------|
| Window type | HWND_MESSAGE vs hidden window 0x0 | Hidden window (0x0) | HWND_MESSAGE NÃO recebe broadcast messages (WM_DEVICECHANGE é broadcast) |
| Message pump | Main thread vs dedicated thread | Thread dedicada | pystray já ocupa a main thread |
| Shutdown | DestroyWindow vs WM_QUIT | PostMessage(WM_QUIT) | Encerra message pump graciosamente |
| Re-contagem | Dentro do WNDPROC vs lazy | No WNDPROC callback | Precisa comparar com baseline imediatamente ao receber evento |
| Thread safety | Lock vs threading.Event | threading.Event / bool atômico | GIL do Python garante atomicidade de bool assignment |

## Módulos Afetados
| Arquivo | Mudança |
|---------|---------|
| `like-move/like_move/device_monitor.py` | REWRITE: adicionada classe `DeviceMonitor` com hidden window + WNDPROC + message pump em thread dedicada. `DeviceBaseline` e funções utilitárias mantidas. |
| `like-move/like_move/jiggler.py` | AJUSTADO: MonitorThread consome `DeviceMonitor.device_disconnected` (property) em vez de pollar DeviceBaseline |
| `like-move/like_move/tray.py` | AJUSTADO: gerencia lifecycle do DeviceMonitor (start/stop quando modo muda) |
| `like-move/like_move/config.py` | Sem mudança |
| `like-move/like_move/detector.py` | Sem mudança |

## Arquitetura Event-Driven
```
WM_DEVICECHANGE (broadcast Windows)
  ↓
Hidden window (0x0) WNDPROC callback
  ↓
DBT_DEVICEREMOVECOMPLETE / DBT_DEVNODES_CHANGED
  ↓
Re-conta dispositivos (GetSystemMetrics + GetRawInputDeviceList)
  ↓
Compara com baseline → seta flag device_disconnected
  ↓
MonitorThread lê flag (property, sem API call) → jiggle
```

## Pipeline
- **Template**: research-first (3 steps)
- **Step 1** (researcher, 6min): Pesquisou APIs, descobriu que HWND_MESSAGE não recebe broadcasts, documentou arquitetura completa
- **Step 2** (implementor, 6min): Rewrite device_monitor.py, ajustes jiggler.py e tray.py, commit f0cd97c
- **Step 3** (validator, 1min): Compile + lint OK, sem correções necessárias
- **Duração total**: ~13 min
- **Auto-merge**: sim

## Lição Aprendida
- **HWND_MESSAGE (message-only windows) NÃO recebe broadcast messages.** WM_DEVICECHANGE é broadcast, então requer hidden top-level window. Documentado pela Microsoft mas fácil de perder.
