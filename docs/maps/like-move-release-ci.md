# Task Map: like-move-release-ci

## Intent
Criar GitHub Actions workflow para build/release automática do .exe + reescrever README para publicação + adicionar LICENSE MIT.

## Arquivos Criados
| Arquivo | Propósito |
|---------|-----------|
| `.github/workflows/release.yml` | CI/CD: build .exe via PyInstaller + criar GitHub Release com asset no push de tag `v*` |
| `LICENSE` | Licença MIT, Allan Santos, 2026 |

## Arquivos Modificados
| Arquivo | Mudança |
|---------|---------|
| `like-move/README.md` | Reescrito completo em PT-BR para publicação: badges, 4 modos, download, build, contribuição |

## Decisões de Design
| Decisão | Escolha | Motivo |
|---------|---------|--------|
| Trigger | Push de tag `v*` | Padrão para releases versionadas |
| Runner | windows-latest | Projeto Windows-only, PyInstaller gera .exe nativo |
| Release action | softprops/action-gh-release@v2 | Mais usado, suporta upload de assets |
| Pip caching | actions/setup-python cache: pip | Acelera builds subsequentes |
| Permissões | contents: write | Necessário para criar release |
| Badges | Estáticos (shields.io) | Repo pode ser privado inicialmente |
| Idioma README | PT-BR | Projeto pessoal do user |
| Licença | MIT | Permissiva, padrão para open source |

## Workflow release.yml
```
trigger: push tag v*
  → checkout
  → setup python 3.12 (com cache pip)
  → pip install requirements.txt + pyinstaller
  → cd like-move && python -m PyInstaller like-move.spec --noconfirm
  → softprops/action-gh-release@v2 com like-move/dist/like-move.exe
```

## Pipeline
- **Template**: research-first (3 steps)
- **Step 1** (researcher, 2min): Pesquisou softprops/action-gh-release, pip caching, working-directory
- **Step 2** (implementor, 2min): Criou workflow + README + LICENSE, commit 3aa37a7
- **Step 3** (validator): Compile + lint limpos
- **Duração total**: ~6 min

## Próximos Passos (do user)
1. Criar repo no GitHub: `gh repo create like-move --public`
2. Adicionar remote: `git remote add origin <url>`
3. Push: `git push -u origin master`
4. Tag + push pra trigger release: `git tag v1.0.0 && git push origin v1.0.0`
