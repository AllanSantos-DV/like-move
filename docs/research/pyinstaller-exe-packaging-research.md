# PyInstaller .exe Packaging Research

## Objetivo
Empacotar `like-move` como `.exe` standalone usando PyInstaller para distribuição em máquinas Windows sem Python instalado.

---

## 1. Análise do Projeto

### Entry Point
- `main.pyw` — script principal (usa extensão `.pyw` para suprimir console)
- Função `main()` no `if __name__ == "__main__":`

### Dependências Python
- **pystray** >= 0.19.0 (v0.19.5 instalada) — system tray icon
- **Pillow** >= 9.0.0 (v12.2.0 instalada) — gera ícone do tray em runtime

### APIs Win32 (ctypes)
O projeto usa exclusivamente `ctypes` (NÃO pywin32):
- `ctypes.windll.user32` — GetLastInputInfo, SendInput, GetSystemMetrics, GetRawInputDeviceList, RegisterClassExW, CreateWindowExW, mensagens de janela
- `ctypes.windll.kernel32` — GetTickCount64, GetModuleHandleW, GetCurrentThreadId
- Hidden window + message pump para WM_DEVICECHANGE (device_monitor.py)

### Estrutura de Módulos
```
main.pyw                    # entry point
like_move/
├── __init__.py             # __version__ = "1.0.0"
├── config.py               # constantes + JigglerState + TriggerMode enum
├── detector.py             # idle detection + screen lock (ctypes)
├── jiggler.py              # SendInput mouse jiggle + MonitorThread
├── device_monitor.py       # WM_DEVICECHANGE hidden window (ctypes)
└── tray.py                 # pystray Icon + Pillow icon generation
```

---

## 2. Pesquisa PyInstaller

### 2.1 Hooks Existentes

#### PIL/Pillow (hook-PIL.py + hook-PIL.Image.py)
PyInstaller inclui hooks nativos para Pillow:
- **hook-PIL.py**: Exclui `tkinter`, `PyQt5`, `PySide2`, `PyQt6`, `PySide6`, `IPython` para reduzir tamanho
- **hook-PIL.Image.py**: Coleta automaticamente todos os submodules com "ImagePlugin" no nome via `collect_submodules('PIL', lambda name: 'ImagePlugin' in name)`

**Conclusão**: Pillow é bem suportado. Nenhum hidden import manual necessário.

#### pystray (hook-pystray.py — pyinstaller-hooks-contrib)
O pacote `pyinstaller-hooks-contrib` inclui um hook para pystray:
```python
from PyInstaller.utils.hooks import collect_submodules
hiddenimports = collect_submodules("pystray")
```

**Análise**: O hook coleta TODOS os submodules do pystray, incluindo backends para todas as plataformas (_darwin, _gtk, _xorg, _appindicator, _win32, _dummy). Isso é necessário porque o `pystray/__init__.py` usa imports dinâmicos dentro de funções locais:
```python
def backend():
    def win32():
        from . import _win32 as backend; return backend
    # ... outros backends ...
    if sys.platform == 'win32':
        candidates = [win32]
```

O PyInstaller não consegue detectar esses imports estáticos, então o hook garante que todos são incluídos. Na prática, no Windows, apenas `_win32` será usado, mas os outros não adicionam muito ao tamanho.

**Conclusão**: pystray funciona com PyInstaller desde que `pyinstaller-hooks-contrib` esteja instalado (vem por padrão com PyInstaller).

### 2.2 ctypes e Win32 API
- **ctypes é parte da stdlib** — PyInstaller embute a stdlib automaticamente
- **Nenhuma DLL externa** necessária — user32.dll e kernel32.dll são sempre presentes no Windows
- **Hidden window (WM_DEVICECHANGE)** — funciona normalmente com `--onefile` pois é criada via ctypes em runtime, não depende de recursos embarcados
- **Nenhum hidden import necessário** para ctypes

### 2.3 Opção --onefile
- Cria um único `.exe` autoextraível
- Na execução, extrai para uma pasta temporária `_MEIxxxxxx` no `%TEMP%`
- Funciona bem para apps simples como o like-move
- **Risco**: Antivírus podem alertar sobre .exe gerados pelo PyInstaller (falso positivo comum)
- **Startup time**: Ligeiramente mais lento que `--onedir` devido à extração

### 2.4 Opção --windowed / --noconsole
- Essencial para o like-move (app de tray sem console)
- Equivalente ao uso de `pythonw.exe` no desenvolvimento
- **Debug**: Se o .exe falhar, re-empacotar sem `--windowed` para ver erros no console

### 2.5 Exclusões para Reduzir Tamanho
Módulos que podem ser excluídos (não usados pelo like-move):
- `tkinter` — já excluído pelo hook-PIL.py
- `unittest`, `test` — frameworks de teste
- `email`, `html`, `http`, `xmlrpc` — networking/web não utilizado
- `distutils`, `setuptools` — ferramentas de build
- `multiprocessing` — não usado
- `asyncio` — não usado (usa threading)

### 2.6 Spec File vs Command Line
Recomendado usar spec file para:
- Documentar a configuração de build permanentemente
- Facilitar reprodução do build
- Configurar hidden imports e exclusões de forma organizada

---

## 3. Plano de Implementação

### 3.1 Arquivos a Criar

| Arquivo | Descrição |
|---------|-----------|
| `like-move/assets/like-move.ico` | Ícone multi-resolução (16,32,48,256) gerado via Pillow |
| `like-move/like-move.spec` | Spec file do PyInstaller |
| `like-move/build.ps1` | Script PowerShell para build automatizado |
| `like-move/scripts/generate_ico.py` | Script para gerar o .ico via Pillow (opcional, pode ser inline no build.ps1) |

### 3.2 Arquivos a Modificar

| Arquivo | Modificação |
|---------|-------------|
| `like-move/.gitignore` | Adicionar `*.spec` (se desejado), confirmar `build/`, `dist/` já presentes |
| `like-move/README.md` | Adicionar seção "Build" com instruções para gerar .exe |

### 3.3 .gitignore — Estado Atual
O `.gitignore` JÁ contém:
- `__pycache__/` ✅
- `dist/` ✅
- `build/` ✅

Adicionar:
- `*.spec` — NÃO! O spec file DEVE ser commitado (é configuração de build, não artefato)
- Nada a adicionar — o .gitignore já está adequado

### 3.4 Spec File (like-move.spec)

Estrutura planejada:
```python
# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['main.pyw'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'pystray._win32',
        'pystray._base',
        'pystray._util',
        'pystray._util.win32',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', '_tkinter',
        'unittest', 'test',
        'distutils', 'setuptools',
        'email', 'html', 'http', 'xmlrpc',
        'multiprocessing',
        'asyncio',
        'pydoc',
        'doctest',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='like-move',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # --windowed
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/like-move.ico'],
)
```

**Notas sobre o spec file**:
- `hiddenimports`: Lista explícita dos módulos pystray necessários no Windows. O hook do contrib já coleta todos, mas listar explicitamente é mais seguro e documentado.
- `excludes`: Lista de módulos stdlib não utilizados para reduzir tamanho do .exe
- `console=False`: Equivalente a `--windowed`
- `strip=False`: Não recomendado no Windows
- `upx=True`: Comprime binários se UPX estiver disponível (reduz ~30% do tamanho)
- **NÃO há datas para embarclar** — o ícone do tray é gerado em runtime via Pillow, não é um recurso estático

### 3.5 Geração do .ico

O tray.py já contém `create_icon_image()` que gera o ícone via Pillow em runtime. Para o .ico do .exe, podemos reusar a mesma lógica:

```python
# generate_ico.py - ideia do script
from PIL import Image, ImageDraw

def create_cursor_icon(size, bg_color, fg_color):
    image = Image.new("RGBA", (size, size), bg_color)
    draw = ImageDraw.Draw(image)
    # Escalar os pontos do cursor proporcionalmente
    scale = size / 64
    arrow_points = [(int(x*scale), int(y*scale)) for x, y in [
        (16, 12), (16, 52), (28, 40), (36, 52), (42, 46), (34, 34), (48, 30)
    ]]
    draw.polygon(arrow_points, fill=fg_color)
    return image

sizes = [16, 32, 48, 256]
images = [create_cursor_icon(s, "#2ecc71", "#ffffff") for s in sizes]
images[0].save("assets/like-move.ico", format="ICO", sizes=[(s,s) for s in sizes], append_images=images[1:])
```

**Nota**: O .ico precisa ter múltiplas resoluções. Pillow suporta salvar .ico com `append_images`.

### 3.6 Script de Build (build.ps1)

Funcionalidades planejadas:
1. Verificar se PyInstaller está instalado, instalar se necessário
2. Gerar o .ico se não existir (executar generate_ico.py)
3. Rodar `pyinstaller like-move.spec --noconfirm --clean`
4. Verificar se dist/like-move.exe foi gerado
5. Mostrar tamanho do arquivo final

### 3.7 README.md — Seção Build

Adicionar ao final (antes de "## Licença"):
```markdown
## Build (.exe)

Para gerar o executável standalone:

```powershell
# Requer Python 3.8+ instalado
.\build.ps1
```

O arquivo `dist/like-move.exe` é gerado. Pode ser executado em qualquer Windows (7/8/10/11) sem Python instalado.

### Build manual

```bash
pip install --user pyinstaller
pyinstaller like-move.spec --noconfirm --clean
```
```

---

## 4. Riscos Identificados

### 4.1 Falso Positivo de Antivírus
- **Risco**: ALTO — Executáveis gerados pelo PyInstaller são frequentemente flagrados por antivírus (especialmente Windows Defender)
- **Mitigação**: Code signing com certificado válido (requer certificado pago) ou instruir usuários a adicionar exceção
- **Alternativa futura**: Considerar Nuitka como alternativa ao PyInstaller (compila para C, menos detecções)

### 4.2 Tamanho do .exe
- **Estimativa**: 15-25 MB (Python runtime + Pillow + pystray + stdlib)
- **Com UPX**: 10-18 MB
- **Mitigação**: Usar `excludes` agressivo para remover módulos não utilizados

### 4.3 Startup Time
- **Risco**: BAIXO — `--onefile` extrai para pasta temporária no primeiro uso (~1-3s)
- Subsequentes execuções podem ser mais rápidas se o cache de extração não for limpo
- **Aceitável** para um app que roda continuamente em background

### 4.4 pystray Backend Detection
- **Risco**: MÉDIO — O `pystray/__init__.py` usa imports dinâmicos via funções locais
- **Mitigação**: Hook do `pyinstaller-hooks-contrib` já trata isso via `collect_submodules("pystray")`
- **Backup**: Hidden imports explícitos no spec file para redundância

### 4.5 Pillow Image Plugins
- **Risco**: BAIXO — Hook nativo do PyInstaller coleta todos os ImagePlugins
- **Nota**: O like-move usa apenas `Image.new()` e `ImageDraw.Draw()` (não carrega imagens de arquivo), então plugins de imagem são technicamente desnecessários, mas não causam problemas além de tamanho extra

### 4.6 Hidden Window + Message Pump
- **Risco**: MUITO BAIXO — Usa apenas ctypes para criar janela e rodar message pump
- Funciona normalmente com `--onefile` e `--windowed`
- Nenhuma dependência de recursos embarcados

### 4.7 Python 3.14 Compatibility
- **Risco**: MÉDIO — O sistema está rodando Python 3.14, que é muito recente
- PyInstaller pode não ter suporte completo para Python 3.14 ainda
- **Mitigação**: Verificar versão compatível do PyInstaller; considerar Python 3.12 ou 3.13 para build se necessário

---

## 5. Ordem de Implementação

1. **Criar `scripts/generate_ico.py`** — Script para gerar o ícone .ico
2. **Criar `assets/` e gerar `assets/like-move.ico`** — Rodar o script de geração
3. **Instalar PyInstaller** — `pip install --user pyinstaller`
4. **Criar `like-move.spec`** — Spec file com toda a configuração
5. **Criar `build.ps1`** — Script de build automatizado
6. **Testar build** — Rodar `pyinstaller like-move.spec` e verificar que .exe é gerado
7. **Atualizar `README.md`** — Adicionar seção Build
8. **Verificar `.gitignore`** — Já está adequado, nada a adicionar
9. **Git commit** — Commitar todos os novos arquivos

---

## 6. Dependências de Build

| Pacote | Versão | Propósito |
|--------|--------|-----------|
| PyInstaller | >= 6.0 | Empacotamento .exe |
| pyinstaller-hooks-contrib | (dependência do PyInstaller) | Hooks para pystray |
| UPX (opcional) | >= 4.0 | Compressão de binários |

---

## 7. Fontes Consultadas

- [PyInstaller Spec Files](https://pyinstaller.org/en/stable/spec-files.html)
- [PyInstaller Usage](https://pyinstaller.org/en/stable/usage.html)
- [PyInstaller When Things Go Wrong](https://pyinstaller.org/en/stable/when-things-go-wrong.html)
- [PyInstaller Hooks](https://pyinstaller.org/en/stable/hooks.html)
- [PyInstaller Recipes Wiki](https://github.com/pyinstaller/pyinstaller/wiki/Recipes)
- [pystray source (GitHub)](https://github.com/moses-palmer/pystray) — __init__.py, _win32.py, _base.py, _util/
- [pyinstaller-hooks-contrib hook-pystray.py](https://github.com/pyinstaller/pyinstaller-hooks-contrib/blob/master/_pyinstaller_hooks_contrib/stdhooks/hook-pystray.py)
- [PyInstaller hook-PIL.py](https://github.com/pyinstaller/pyinstaller/blob/develop/PyInstaller/hooks/hook-PIL.py)
- [PyInstaller hook-PIL.Image.py](https://github.com/pyinstaller/pyinstaller/blob/develop/PyInstaller/hooks/hook-PIL.Image.py)
