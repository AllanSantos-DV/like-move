# like-move 🖱️

Mouse jiggler inteligente para Windows que previne bloqueio de tela por inatividade.

## Para quê serve?

Se você tem 2 PCs (ex: desktop + notebook) compartilhando 1 tela/mouse/teclado via **KVM switch**, quando alterna pro desktop, o notebook bloqueia a tela por inatividade. O **like-move** resolve isso fazendo micro-movimentos do mouse quando detecta que você não está usando aquele PC.

## Como funciona

1. **Detecta inatividade** — Monitora o tempo desde o último input real (mouse/teclado) via `GetLastInputInfo` (Win32 API)
2. **Faz jiggle** — Quando idle > threshold (padrão: 30s), move o cursor 1px ida e volta usando `SendInput` — imperceptível, mas reseta o timer de inatividade do Windows
3. **Detecta tela bloqueada** — Se a tela já está bloqueada, não faz jiggle (seria inútil)
4. **Roda na bandeja** — Ícone na system tray com menu para ativar/desativar, configurar threshold e sair

## Requisitos

- **Windows** (7, 8, 10, 11)
- **Python 3.8+**
- **Sem necessidade de admin** — todas as APIs usadas são user-space

## Instalação

```bash
# Instalar dependências (--user se não tiver admin)
pip install --user -r requirements.txt
```

## Uso

```bash
# Com janela de console (útil para debug/logs)
python main.pyw

# Sem janela de console (uso normal)
pythonw main.pyw
```

O ícone aparece na bandeja do sistema (system tray):
- 🟢 **Verde** = ativo
- ⚫ **Cinza** = pausado

### Menu do tray

| Opção | Descrição |
|-------|-----------|
| ✓ Ativo / ✗ Pausado | Liga/desliga o jiggler |
| Threshold | Configura tempo de inatividade (15s, 30s, 1min, 2min, 5min) |
| Sair | Encerra o programa |

## Como funciona por baixo

| Componente | API Win32 | Descrição |
|-----------|-----------|-----------|
| Detecção de idle | `GetLastInputInfo` + `GetTickCount64` | Calcula tempo desde último input |
| Detecção de tela bloqueada | `OpenInputDesktopW` | Retorna NULL quando tela está no Secure Desktop |
| Mouse jiggle | `SendInput` (MOUSEEVENTF_MOVE) | Movimento relativo +1px/-1px — mais confiável que SetCursorPos |

## Configuração

Os valores padrão estão em `like_move/config.py`:

| Parâmetro | Padrão | Descrição |
|-----------|--------|-----------|
| `IDLE_THRESHOLD_SECONDS` | 30 | Segundos de inatividade antes de iniciar jiggle |
| `JIGGLE_INTERVAL_SECONDS` | 10 | Intervalo entre jiggles enquanto idle |
| `CHECK_INTERVAL_SECONDS` | 1 | Intervalo de checagem do estado |
| `JIGGLE_PIXELS` | 1 | Pixels de movimento (ida e volta) |

## Arquitetura

```
main.pyw              → Entry point (sem console com pythonw)
like_move/
├── config.py         → Constantes de configuração
├── detector.py       → Detecção de idle e tela bloqueada (ctypes)
├── jiggler.py        → Lógica de jiggle via SendInput + thread de monitoramento
└── tray.py           → System tray icon com pystray
```

- **Thread principal**: event loop do pystray (system tray)
- **Thread daemon**: loop de monitoramento que checa idle e faz jiggle

## Licença

MIT
