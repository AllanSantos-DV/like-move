# Research: Splash Screen com Animação + Toast Notification

**Data:** 2026-04-10
**Escopo:** Adicionar splash screen com fade-in e toast notification nativa ao like-move
**Status:** Pesquisa completa — pronto para implementação

---

## 1. Estado Atual do Projeto

### Arquitetura
- **Entry point:** `main.pyw` → `TrayApp().run()` (blocking)
- **Tray:** `like_move/tray.py` — pystray `Icon` com menu, `_setup()` callback em thread separada
- **Dependências:** pystray ≥0.19.0, Pillow ≥9.0.0
- **Win32 via ctypes:** já usado em `detector.py` (GetLastInputInfo, OpenInputDesktop) e `device_monitor.py`
- **PyInstaller spec:** onefile, noconsole, `tkinter` nos excludes, embeds `assets/like-move.ico`
- **Versão:** `__version__ = "1.0.0"` em `__init__.py`

### Fluxo atual
```
main.pyw → main() → TrayApp() → icon.run(setup=_setup)
                                          ↓
                                    _setup(icon):
                                      icon.visible = True
                                      MonitorThread.start()
                                      DeviceMonitor (se KVM)
```

---

## 2. Toast Notification — Análise de Opções

### Opção A: winotify (lib externa)
- **Como funciona:** Gera script PowerShell inline que usa `Windows.UI.Notifications.ToastNotificationManager` via COM/WinRT. Executa `powershell.exe` como subprocess.
- **Prós:** Toast moderno (Action Center), botões de ação, ícone customizado
- **Contras:**
  - Dependência extra (precisa adicionar a requirements.txt e hidden imports)
  - Lança subprocess `powershell.exe` — overhead de ~200-500ms
  - Pode falhar em ambientes restritos (ExecutionPolicy)
  - Ícone deve ser path absoluto — complicado com PyInstaller onefile (temp dir)
  - Complexidade desnecessária para uma notificação simples
- **Veredicto:** ❌ Descartada — over-engineered para o caso de uso

### Opção B: pystray.Icon.notify() ⭐ RECOMENDADA
- **Descoberta:** pystray **já tem** método `notify(message, title=None)` na classe base (`_base.py`)
- **Implementação Win32** (em `_win32.py`):
  ```python
  def _notify(self, message, title=None):
      self._message(
          win32.NIM_MODIFY,
          win32.NIF_INFO,
          szInfo=message,
          szInfoTitle=title or self.title or '')
  ```
- **Mecanismo:** Usa `Shell_NotifyIcon(NIM_MODIFY, NIF_INFO)` — balloon notification nativa do Windows
- **No Windows 10/11:** Balloon tips são automaticamente convertidos em toast notifications pelo OS
- **Prós:**
  - Zero dependências extras
  - Já integrado com o ícone do tray (usa o mesmo NOTIFYICONDATA)
  - Funciona perfeitamente com PyInstaller onefile
  - Uma linha de código para implementar
  - Tem `remove_notification()` para limpar
  - `HAS_NOTIFICATION = True` no backend Win32
- **Contras:**
  - Não fica no Action Center no Win11 (balloon transiente)
  - Sem botões de ação (apenas texto)
  - Visual dependente da versão do Windows
- **Veredicto:** ✅ **Melhor opção** — zero overhead, já disponível

### Opção C: ctypes + Shell_NotifyIconW direto
- **Como funciona:** Chamada direta a `Shell_NotifyIconW` com struct `NOTIFYICONDATA` incluindo `szInfo`/`szInfoTitle`
- **Prós:** Sem dependências, controle total
- **Contras:** É exatamente o que pystray já faz internamente — reimplementação desnecessária
- **Veredicto:** ❌ Descartada — pystray já faz isso

### Decisão Final Toast: **pystray.Icon.notify()**
- Chamar `icon.notify("like-move está rodando — clique direito para configurar", "like-move")` no `_setup()`
- Após `icon.visible = True` para garantir que o ícone está visível

---

## 3. Splash Screen — Análise de Opções

### Opção A: Win32 puro via ctypes
- **Como funciona:** `CreateWindowEx` com `WS_POPUP | WS_EX_LAYERED`, `SetLayeredWindowAttributes` para fade, message loop próprio
- **Prós:** Sem dependências novas, consistente com o projeto
- **Contras:** 
  - Muito complexo (RegisterClassEx, WndProc, message pump, GDI para texto)
  - Renderizar texto com GDI requer SelectObject, TextOut, CreateFont — verboso
  - Difícil de manter
- **Veredicto:** ⚠️ Viável mas desnecessariamente complexo para o conteúdo visual

### Opção B: tkinter (stdlib)
- **Como funciona:** `Tk()` root window com `overrideredirect(1)`, `attributes('-alpha', x)` para fade
- **Prós:** Simples de implementar, stdlib Python
- **Contras:**
  - **Atualmente excluído no spec file** (`excludes: ['tkinter', '_tkinter']`)
  - Adicionar tkinter aumenta o .exe em **~10-15MB** (TCL/TK runtime)
  - Contradiz a filosofia do projeto (mínimo de deps)
  - Pode ter conflitos com o event loop do pystray em alguns cenários
- **Veredicto:** ❌ Descartada — impacto no tamanho do executável inaceitável

### Opção C: Pillow + Win32 via ctypes ⭐ RECOMENDADA
- **Como funciona:**
  1. Pillow (já é dependência) renderiza a imagem do splash: logo, texto, versão, barra de loading
  2. Win32 `CreateWindowEx` com `WS_EX_LAYERED | WS_EX_TOPMOST` cria janela borderless
  3. `UpdateLayeredWindow` com `BLENDFUNCTION` exibe a imagem com per-pixel alpha
  4. Fade-in: chamadas repetidas de `SetLayeredWindowAttributes(alpha=0→255)` em steps
  5. Message loop mínimo com `SetTimer` para controle do tempo
  6. Auto-fecha após 2-3 segundos
- **Prós:**
  - Zero dependências novas (Pillow já incluída, ctypes é stdlib)
  - Pillow simplifica enormemente a renderização (ImageDraw, ImageFont)
  - Per-pixel alpha possível via `UpdateLayeredWindow` (cantos arredondados, sombra)
  - Consistente com a abordagem do projeto (ctypes para Win32)
  - Não afeta tamanho do .exe
- **Contras:**
  - Precisa converter Pillow Image → HBITMAP (via tobytes + CreateDIBSection ou CreateBitmap)
  - Message loop próprio (mas é simples e blocking — ideal para splash)
  - Fonte do texto limitada ao padrão do sistema (a menos que use Pillow.ImageFont)
- **Win32 APIs necessárias:**
  - `RegisterClassEx`, `CreateWindowEx` (WS_POPUP, WS_EX_LAYERED, WS_EX_TOPMOST)
  - `SetLayeredWindowAttributes` (LWA_ALPHA = 0x02) para fade
  - `GetSystemMetrics` (SM_CXSCREEN, SM_CYSCREEN) para centralizar
  - `SetTimer` / `KillTimer` para controle de tempo
  - `PeekMessage`, `TranslateMessage`, `DispatchMessage` para message loop
  - `GetDC`, `CreateCompatibleDC`, `SelectObject`, `BitBlt` para pintar
  - `CreateDIBSection` para converter Pillow → HBITMAP (ou `SetDIBitsToDevice`)
  - `DestroyWindow`, `UnregisterClass` para cleanup
- **Veredicto:** ✅ **Melhor opção** — equilíbrio perfeito entre simplicidade e controle

### Decisão Final Splash: **Pillow (renderização) + Win32 ctypes (janela + animação)**

---

## 4. Detalhes Técnicos da Implementação

### 4.1 Splash Screen (`like_move/splash.py`)

#### Conteúdo visual (renderizado com Pillow)
- Tamanho: ~300×200px
- Background: gradiente ou cor sólida (#1a1a2e ou similar dark theme)
- Ícone: carregar `assets/like-move.ico` via `Image.open()` (Pillow suporta ICO)
- Texto: "like-move" (título) + `__version__` (subtítulo)
- Animação: barra de loading simples (dots pulsantes ou progress bar)
- Cantos: opcionalmente arredondados (Pillow ImageDraw.rounded_rectangle)

#### Fluxo da splash
```
show_splash() [blocking, ~2.5s]:
  1. Renderiza imagem com Pillow (Image + ImageDraw)
  2. Converte Image → HBITMAP via CreateDIBSection
  3. RegisterClassEx + CreateWindowEx (WS_POPUP | WS_EX_LAYERED | WS_EX_TOPMOST)
  4. Centraliza na tela (GetSystemMetrics)
  5. SetTimer(WM_TIMER, 30ms) para animação
  6. Message loop:
     - WM_PAINT: BitBlt do HBITMAP
     - WM_TIMER: incrementa alpha (SetLayeredWindowAttributes) ou atualiza frame
     - Após ~2.5s: PostQuitMessage(0)
  7. Cleanup: KillTimer, DestroyWindow, UnregisterClass, DeleteObject
  8. Retorna
```

#### Fade-in timeline
- 0ms–800ms: alpha 0 → 255 (fade-in, ~25 steps de 32ms)
- 800ms–2200ms: alpha 255, janela totalmente visível
- 2200ms–2500ms: alpha 255 → 0 (fade-out, ~10 steps de 30ms)
- 2500ms: destroy window, return

### 4.2 Toast Notification (em `tray.py`)

#### Integração no `_setup()`
```python
def _setup(self, icon: Icon) -> None:
    self._icon = icon
    icon.visible = True
    
    # Toast notification nativa
    icon.notify(
        "like-move está rodando — clique direito para configurar",
        "like-move"
    )
    
    # Monitor thread (já existente)
    self._monitor = MonitorThread(self._state)
    self._monitor.start()
    self._ensure_device_monitor()
```

### 4.3 Integração no `main.pyw`
```python
def main() -> None:
    if sys.platform != "win32":
        logger.error("like-move só funciona no Windows.")
        sys.exit(1)

    logger.info("Iniciando like-move...")

    # 1. Splash screen (blocking, ~2.5s)
    from like_move.splash import show_splash
    show_splash()

    # 2. Tray app (blocking event loop)
    from like_move.tray import TrayApp
    app = TrayApp()
    try:
        app.run()
    except KeyboardInterrupt:
        logger.info("Interrompido pelo usuário")
    except Exception:
        logger.exception("Erro fatal")
        sys.exit(1)
```

---

## 5. Arquivos a Criar/Modificar

| Ação | Arquivo | Descrição |
|------|---------|-----------|
| **CRIAR** | `like_move/splash.py` | Módulo splash screen (Pillow + Win32 ctypes) |
| **MODIFICAR** | `main.pyw` | Adicionar `show_splash()` antes de `TrayApp().run()` |
| **MODIFICAR** | `like_move/tray.py` | Adicionar `icon.notify()` no `_setup()` |
| Sem alteração | `like-move.spec` | Não precisa mudar (sem deps novas) |
| Sem alteração | `requirements.txt` | Não precisa mudar (sem deps novas) |

---

## 6. Dependências

**Nenhuma dependência nova necessária.**

- Pillow: já em requirements.txt e hidden imports do spec
- ctypes: stdlib Python
- pystray: já em requirements.txt e hidden imports do spec

---

## 7. Riscos Identificados

| Risco | Probabilidade | Impacto | Mitigação |
|-------|---------------|---------|-----------|
| Conversão Pillow→HBITMAP falhar | Baixa | Alto | Usar CreateDIBSection com formato BGRA; testar com imagens RGBA |
| Splash bloquear mais que 3s | Baixa | Médio | Timeout hard-coded no message loop; fallback: skip splash |
| Message loop conflitar com pystray | Muito baixa | Alto | Splash roda e fecha ANTES de pystray.Icon.run(); são sequenciais |
| Balloon notification não aparece | Baixa | Baixo | Depende de configurações do Windows (Focus Assist); é cosmético |
| GDI resource leak | Média | Médio | Cleanup rigoroso no finally; DeleteObject para HBITMAP, DC |
| Pillow ImageFont indisponível | Baixa | Baixo | Usar fonte default do Pillow (bitmap); ou carregar via GDI CreateFont |
| Antialiasing de texto ruim | Baixa | Baixo | Pillow ImageDraw.text() com fill=cor; ou usar truetype se disponível |
| Splash ugly em high-DPI | Média | Baixo | Usar GetSystemMetrics DPI-aware; ou aceitar tamanho fixo (300x200) |

---

## 8. Ordem de Implementação

1. **splash.py** — módulo completo com `show_splash()` exportado
   - Win32 helpers (constantes, structs, funções ctypes)
   - Função de renderização Pillow (imagem do splash)
   - Conversão Pillow Image → HBITMAP
   - Criação da janela Win32 layered
   - Message loop com timer (fade-in → display → fade-out)
   - Cleanup de recursos

2. **tray.py** — adicionar `icon.notify()` no `_setup()`
   - Uma linha após `icon.visible = True`

3. **main.pyw** — adicionar `show_splash()` antes do `TrayApp`
   - Import e chamada entre log e TrayApp()

4. **Testes manuais**
   - Executar `python main.pyw` e verificar splash + toast
   - Build com PyInstaller e verificar o .exe

---

## 9. Referências Consultadas

- **pystray source code** (`_base.py`, `_win32.py`): Confirmado `notify()` e `_notify()` com `NIF_INFO`
- **pystray docs** (readthedocs): Referência de `Icon`, `run()`, `setup` callback
- **winotify** (GitHub + PyPI): Analisado e descartado (PowerShell subprocess, dep extra)
- **Win32 Shell_NotifyIconW** (Microsoft Learn): Balloon/toast via `NIM_MODIFY` + `NIF_INFO`
- **Win32 SetLayeredWindowAttributes** (Microsoft Learn): `WS_EX_LAYERED`, `LWA_ALPHA`, `bAlpha` 0-255
- **Win32 CreateWindowEx** (Microsoft Learn): `WS_POPUP`, `WS_EX_TOPMOST`, `WS_EX_LAYERED`
