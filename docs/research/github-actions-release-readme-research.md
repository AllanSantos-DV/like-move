# Research: GitHub Actions Workflow + README Rewrite + LICENSE

**Data**: 2026-04-10
**Escopo**: CI/CD release pipeline, documentação para publicação, licenciamento

---

## 1. Estado Atual do Codebase

### Estrutura
```
workspace-root/
├── .github/workflows/     ← NÃO EXISTE (criar)
├── LICENSE                ← NÃO EXISTE (criar)
├── docs/research/         ← Documentação de pesquisa
└── like-move/             ← Projeto Python
    ├── main.pyw           ← Entry point
    ├── like_move/
    │   ├── __init__.py    ← __version__ = "1.0.0"
    │   ├── config.py      ← TriggerMode enum (IDLE/KVM/BOTH/ALWAYS), JigglerState
    │   ├── detector.py    ← GetLastInputInfo, OpenInputDesktop (idle + lock detection)
    │   ├── device_monitor.py ← WM_DEVICECHANGE event-driven, hidden window + msg pump
    │   ├── jiggler.py     ← SendInput MOUSEEVENTF_MOVE, MonitorThread
    │   └── tray.py        ← pystray Icon + Menu (toggle, mode, threshold, devices, quit)
    ├── assets/
    │   ├── like-move.ico
    │   └── generate_ico.py
    ├── like-move.spec      ← PyInstaller spec (onefile, noconsole, icon, hidden imports)
    ├── build.ps1           ← Local build script
    ├── requirements.txt    ← pystray>=0.19.0, Pillow>=9.0.0
    ├── README.md           ← Existente (desatualizado — falta KVM/modes/devices)
    └── .gitignore
```

### Features Identificadas (do código-fonte)
1. **4 Trigger Modes** (config.py `TriggerMode` enum):
   - `IDLE` — Jiggle quando idle > threshold via `GetLastInputInfo`
   - `KVM` — Jiggle quando dispositivo desconecta (event-driven via `WM_DEVICECHANGE`)
   - `BOTH` — Qualquer trigger ativa jiggle
   - `ALWAYS` — Jiggle contínuo (controle manual via tray)

2. **Dispositivos KVM monitoráveis** (tray.py `_DEVICE_LABELS`):
   - Monitor (via `GetSystemMetrics(SM_CMONITORS)`)
   - Mouse (via `GetRawInputDeviceList` `RIM_TYPEMOUSE`)
   - Teclado (via `GetRawInputDeviceList` `RIM_TYPEKEYBOARD`)

3. **Detecção de tela bloqueada** (detector.py `is_screen_locked`):
   - `OpenInputDesktop` retorna NULL quando no Secure Desktop

4. **System tray** (tray.py `TrayApp`):
   - Ícone verde (ativo) / cinza (pausado)
   - Menu: Ativo toggle, Modo (radio), Dispositivos KVM (checkboxes, visível se KVM/BOTH), Threshold (radio: 15s/30s/1min/2min/5min), Sair

5. **Event-driven KVM** (device_monitor.py `DeviceMonitor`):
   - Hidden top-level window (não HWND_MESSAGE — broadcast)
   - Message pump em thread dedicada
   - DeviceBaseline para detectar drops vs baseline

6. **Build**: PyInstaller onefile, noconsole, icon custom, UPX enabled

### Dependencies
- Runtime: `pystray>=0.19.0`, `Pillow>=9.0.0`
- Build: `pyinstaller`
- Nenhuma dependência do sistema além de Python e Win32 (ctypes built-in)

---

## 2. Plano de Implementação

### Arquivo 1: `.github/workflows/release.yml` (CRIAR na raiz)

**Caminho**: `<workspace-root>/.github/workflows/release.yml`

**Detalhes do workflow**:
- **Trigger**: `on: push: tags: ['v*']`
- **Permissions**: `contents: write`
- **Job**: `build-release` em `windows-latest`
- **Steps**:
  1. `actions/checkout@v4`
  2. `actions/setup-python@v5` com `python-version: '3.12'`
  3. Install deps: `pip install -r like-move/requirements.txt pyinstaller`
  4. Build: `cd like-move && python -m PyInstaller like-move.spec --noconfirm`
  5. `softprops/action-gh-release@v2` com:
     - `files: like-move/dist/like-move.exe`
     - `name: like-move ${{ github.ref_name }}`
     - `generate_release_notes: true`
     - `draft: false`
     - `prerelease: false`

**Validação da action** (pesquisa confirmada):
- `softprops/action-gh-release@v2` suporta Windows
- `files` aceita paths com `/` e `\` no Windows
- `generate_release_notes: true` gera changelog automático do GitHub
- `permissions: contents: write` é obrigatório
- Token padrão `${{ github.token }}` é usado automaticamente

### Arquivo 2: `like-move/README.md` (REESCREVER)

**Idioma**: Português BR
**Seções planejadas**:
1. **Header**: Nome + emoji + tagline + badges (License MIT, Latest Release, Windows Only)
   - Badges estáticos via shields.io (img.shields.io/badge/...)
   - Badge de release: link relativo `../../releases/latest`
2. **Screenshot/Demo**: Placeholder com comentário HTML para futura imagem
3. **Features**: Lista detalhada dos 4 modos + detecção de tela bloqueada + event-driven
4. **Download**: Link para `../../releases/latest` com instruções simples
5. **Instalação**:
   - Standalone (.exe) — baixar de Releases
   - Desenvolvimento — clone + pip install + pythonw
6. **Uso**: Menu do tray detalhado com tabela:
   - Ativo (toggle com ícone verde/cinza)
   - Modo (Inatividade, KVM, Ambos, Sempre) — radio
   - Dispositivos KVM (Monitor, Mouse, Teclado) — checkboxes, visível em KVM/Both
   - Threshold (15s, 30s, 1min, 2min, 5min) — radio
   - Sair
7. **Modos de Trigger**: Explicação detalhada de cada modo
8. **Dispositivos KVM**: O que cada dispositivo monitora e como funciona
9. **Como funciona**: Tabela técnica com APIs Win32 (GetLastInputInfo, OpenInputDesktop, SendInput, GetSystemMetrics, GetRawInputDeviceList, WM_DEVICECHANGE)
10. **Configuração**: Tabela com parâmetros de config.py
11. **Arquitetura**: Diagrama de módulos
12. **Build**: Instruções locais (build.ps1 + manual) + menção ao CI/GitHub Actions
13. **Contribuição**: Fork + branch + PR
14. **Licença**: MIT com link para LICENSE

**Diferenças vs README atual**:
- README atual NÃO menciona: KVM mode, trigger modes, device monitoring, event-driven, WM_DEVICECHANGE
- README atual NÃO tem: badges, download section, screenshot placeholder, seção de contribuição formal
- README atual é funcional mas incompleto para publicação

### Arquivo 3: `LICENSE` (CRIAR na raiz)

**Caminho**: `<workspace-root>/LICENSE`
- Licença MIT padrão
- Copyright (c) 2026 Allan Santos
- Texto completo da MIT License

---

## 3. Dependências para Implementação

| Item | Tipo | Notas |
|------|------|-------|
| `actions/checkout@v4` | GitHub Action | Estável, amplamente usado |
| `actions/setup-python@v5` | GitHub Action | Suporta Python 3.12 no Windows |
| `softprops/action-gh-release@v2` | GitHub Action | Confirmado: suporte Windows, `files`, `generate_release_notes` |
| Python 3.12 | Runtime CI | Disponível em `windows-latest` |
| PyInstaller | Build tool | Instalado via pip no CI |

---

## 4. Riscos Identificados

### Risco 1: Tamanho do .exe no CI vs local
- **Descrição**: O .exe gerado no CI pode diferir em tamanho do local (~25MB) por versão diferente de Python/PyInstaller
- **Mitigação**: Pinar versão do Python (3.12) e considerar pinar PyInstaller no futuro
- **Severidade**: Baixa

### Risco 2: UPX não disponível no CI
- **Descrição**: O spec tem `upx=True`, mas UPX pode não estar instalado em `windows-latest`
- **Mitigação**: PyInstaller ignora UPX silenciosamente se não encontrado — o exe será ligeiramente maior mas funcional. Se necessário, adicionar step de instalação de UPX no futuro
- **Severidade**: Baixa (funcional, apenas tamanho)

### Risco 3: Paths no workflow cross-platform
- **Descrição**: O workflow roda em `windows-latest`, paths com backslash podem causar problemas no YAML
- **Mitigação**: Usar forward slashes no YAML (GitHub Actions normaliza no Windows). Validado pela doc do softprops que aceita ambos separadores
- **Severidade**: Baixa

### Risco 4: Badge de release quebrada antes do primeiro release
- **Descrição**: Badge de release via shields.io retornará "not found" antes de existir um release
- **Mitigação**: Usar badges estáticas (não dinâmicas) ou aceitar que aparecerá após primeiro release. Para o caso de repo público recém-criado, usar badge estática de platform "Windows" e licença "MIT" que não dependem de releases
- **Severidade**: Insignificante

### Risco 5: `cd like-move` no step de build
- **Descrição**: O comando `cd like-move && python -m PyInstaller like-move.spec --noconfirm` precisa funcionar no shell padrão do Windows runner
- **Mitigação**: No `windows-latest`, o shell padrão é PowerShell. Usar `working-directory: like-move` no step ao invés de `cd`, ou usar `shell: bash` onde `cd && cmd` funciona. Alternativa: `shell: cmd` com `cd`. Recomendação: usar `working-directory: like-move` no step de build
- **Severidade**: Média — testar a abordagem escolhida

---

## 5. Ordem de Implementação

1. **Criar `LICENSE`** na raiz — sem dependências, arquivo standalone
2. **Criar `.github/workflows/release.yml`** na raiz — requer diretório `.github/workflows/`
3. **Reescrever `like-move/README.md`** — última porque referencia o workflow e a licença
4. **Git commit** — `git add -A && git commit` com mensagem descritiva

**Motivo da ordem**: LICENSE é o mais simples e independente. O workflow não depende do README. O README referencia ambos (workflow para CI badge, LICENSE para seção de licença).

---

## 6. Notas Técnicas

### softprops/action-gh-release@v2 — Configuração Validada
```yaml
# Campos confirmados pela documentação oficial:
- files: string (newline-delimited globs)
- name: string (release name, default: tag name)
- generate_release_notes: boolean
- draft: boolean (default: false)
- prerelease: boolean
- token: defaults to ${{ github.token }}
# Permissions requeridas:
permissions:
  contents: write
```

### PyInstaller no CI
- O spec file usa paths relativos (`['main.pyw']`, `'assets/like-move.ico'`)
- Portanto, o build DEVE rodar com CWD = `like-move/`
- Usar `working-directory: like-move` no step é mais limpo que `cd`
- Output: `like-move/dist/like-move.exe` (relativo ao workspace root)

### README — Links Relativos
- Releases: `../../releases/latest` (do README dentro de `like-move/`)
  - Isso navega 2 níveis acima no GitHub (de `like-move/README.md` para repo root, depois para releases)
  - Nota: Se o README principal do repo estiver em `like-move/`, esse path funciona no GitHub web
