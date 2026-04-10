# like-move 🖱️

**Mouse jiggler inteligente para Windows** — previne bloqueio de tela por inatividade, com suporte especial a KVM switches.

![License](https://img.shields.io/badge/license-MIT-blue)
![Release](https://img.shields.io/github/v/release/allansantos/like-move?display_name=tag&label=release)
![Windows Only](https://img.shields.io/badge/platform-Windows-0078D6?logo=windows)

---

## 📸 Screenshot

<!-- TODO: Adicionar screenshot do system tray com menu aberto -->
*Em breve: screenshot do ícone na bandeja com o menu de contexto.*

---

## ✨ Features

- **4 modos de trigger**: Inatividade, KVM (event-driven), Ambos ou Sempre
- **Detecção de KVM via eventos do Windows** — usa `WM_DEVICECHANGE` (event-driven, sem polling)
- **Detecção de tela bloqueada** — não faz jiggle desnecessário quando a tela já está no Secure Desktop
- **System tray** — ícone colorido (🟢 ativo / ⚫ pausado) com menu completo
- **Configurável** — threshold de inatividade, dispositivos monitorados, modo de trigger
- **Standalone** — executável `.exe` único via PyInstaller, sem dependências externas
- **Sem admin** — todas as APIs são user-space (Win32 via ctypes)

---

## 📥 Download

Baixe a versão mais recente na [página de releases](../../releases/latest):

> **[⬇ like-move.exe](../../releases/latest)** — executável standalone, não requer Python nem instalação.

Basta baixar e executar. O ícone aparece na bandeja do sistema (system tray).

---

## 🚀 Instalação

### Executável standalone (recomendado)

1. Baixe `like-move.exe` na [página de releases](../../releases/latest)
2. Execute — o ícone aparece na bandeja do sistema
3. Pronto! Não requer Python, admin ou instalação

### Desenvolvimento (Python)

```bash
# Clonar repositório
git clone https://github.com/allansantos/like-move.git
cd like-move/like-move

# Instalar dependências
pip install -r requirements.txt

# Executar (sem janela de console)
pythonw main.pyw

# Ou com console (útil para debug/logs)
python main.pyw
```

**Requisitos**: Windows 7/8/10/11 · Python 3.8+

---

## 🖥️ Uso

Ao executar, o like-move aparece como ícone na bandeja do sistema:

| Ícone | Estado |
|-------|--------|
| 🟢 Verde | Ativo — monitorando e fazendo jiggle quando necessário |
| ⚫ Cinza | Pausado — nenhum jiggle sendo feito |

### Menu do tray

| Opção | Descrição |
|-------|-----------|
| **Ativo** | Liga/desliga o jiggler (checkbox) |
| **Modo →** | Seleciona modo de trigger (Inatividade, KVM, Ambos, Sempre) |
| **Dispositivos KVM →** | Seleciona quais dispositivos monitorar (visível nos modos KVM/Ambos) |
| **Threshold →** | Tempo de inatividade antes do jiggle (15s, 30s, 1min, 2min, 5min) |
| **Sair** | Encerra o programa |

---

## 🎯 Modos de Trigger

| Modo | Comportamento |
|------|--------------|
| **Inatividade** | Jiggle quando o tempo sem input (mouse/teclado) ultrapassa o threshold. Modo clássico de mouse jiggler. |
| **KVM** | Jiggle quando um dispositivo monitorado desconecta (ex: KVM trocou para outro PC). Usa `WM_DEVICECHANGE` — event-driven, sem polling. |
| **Ambos** | Ativa o jiggle se **qualquer** condição for atendida (inatividade OU desconexão KVM). |
| **Sempre** | Jiggle contínuo enquanto o programa estiver ativo. Controle manual via toggle no tray. |

---

## 🔌 Dispositivos KVM

Nos modos **KVM** e **Ambos**, você pode selecionar quais dispositivos monitorar:

| Dispositivo | O que monitora | API |
|-------------|---------------|-----|
| **Monitor** | Contagem de monitores conectados | `GetSystemMetrics(SM_CMONITORS)` |
| **Mouse** | Dispositivos de mouse raw input | `GetRawInputDeviceList` (RIM_TYPEMOUSE) |
| **Teclado** | Dispositivos de teclado raw input | `GetRawInputDeviceList` (RIM_TYPEKEYBOARD) |

O like-move captura uma **baseline** na inicialização. Se a contagem de algum dispositivo monitorado cair abaixo da baseline, considera-se uma desconexão (= KVM trocou para outro PC) e o jiggle é ativado.

---

## ⚙️ Configuração

Os valores padrão estão em `like_move/config.py`:

| Parâmetro | Padrão | Descrição |
|-----------|--------|-----------|
| `IDLE_THRESHOLD_SECONDS` | 30 | Segundos de inatividade antes de iniciar jiggle |
| `JIGGLE_INTERVAL_SECONDS` | 10 | Intervalo entre jiggles enquanto idle |
| `CHECK_INTERVAL_SECONDS` | 1 | Intervalo de checagem do estado |
| `JIGGLE_PIXELS` | 1 | Pixels de movimento (ida e volta) |

---

## 🔧 Como funciona

O like-move usa exclusivamente APIs Win32 via `ctypes` — sem `pywin32`, sem dependências nativas.

| Componente | API Win32 | Descrição |
|-----------|-----------|-----------|
| Detecção de idle | `GetLastInputInfo` + `GetTickCount64` | Calcula tempo desde último input real |
| Detecção de tela bloqueada | `OpenInputDesktopW` | Retorna `NULL` quando a tela está no Secure Desktop |
| Mouse jiggle | `SendInput` (`MOUSEEVENTF_MOVE`) | Movimento relativo +1px/−1px — imperceptível, reseta timer do Windows |
| Detecção de KVM | `WM_DEVICECHANGE` + hidden window | Event-driven: janela oculta recebe broadcasts de mudança de dispositivo |
| Contagem de dispositivos | `GetSystemMetrics`, `GetRawInputDeviceList` | Monitores, mouses e teclados conectados |

### Arquitetura

```
main.pyw                  → Entry point (sem console com pythonw)
like_move/
├── config.py             → Constantes e estado mutável (TriggerMode, JigglerState)
├── detector.py           → Detecção de idle e tela bloqueada (ctypes)
├── device_monitor.py     → Monitor de dispositivos event-driven (WM_DEVICECHANGE)
├── jiggler.py            → Lógica de jiggle via SendInput + thread de monitoramento
└── tray.py               → System tray icon com pystray + menu configurável
```

**Threads:**
- **Principal** — event loop do pystray (system tray)
- **Monitor** — thread daemon que checa idle/KVM e faz jiggle
- **DeviceMonitor** — thread daemon com message pump Win32 para `WM_DEVICECHANGE`

---

## 🏗️ Build

### Build local

```powershell
# Instalar dependências
pip install -r requirements.txt pyinstaller

# Build via script
.\build.ps1

# Ou build manual
python -m PyInstaller like-move.spec --noconfirm
```

O executável é gerado em `dist/like-move.exe` (~25 MB, standalone).

### CI/CD

O repositório inclui GitHub Actions workflow que gera automaticamente uma release com o `.exe` ao criar uma tag `v*`:

```bash
git tag v1.0.0
git push origin v1.0.0
# → GitHub Actions builda e publica like-move.exe na release
```

### Regenerar ícone

```bash
python assets/generate_ico.py
```

---

## 🤝 Contribuição

1. Fork o repositório
2. Crie uma branch para sua feature (`git checkout -b feature/minha-feature`)
3. Commit suas mudanças (`git commit -m 'feat: minha feature'`)
4. Push para a branch (`git push origin feature/minha-feature`)
5. Abra um Pull Request

---

## 📄 Licença

[MIT](../LICENSE) © Allan Santos
