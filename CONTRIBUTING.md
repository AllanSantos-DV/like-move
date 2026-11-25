# Contribuindo com o like-move

O like-move mantém o Windows acordado com `SetThreadExecutionState`, sem simular entrada. Antes de mudar algo, leia o `README.md`.

## Ambiente

- Windows, Python 3.9 ou mais novo, Node 18 ou mais novo para o pacote `npm`.
- Dependências do app: `pip install -r like-move/requirements.txt`.

## Testes

Rode da pasta `like-move/`:

```
python -m unittest discover -s tests
cd npm && npm test
```

Os testes não abrem janela, não tocam áudio e não escrevem na configuração real (usam um `APPDATA` temporário).

## Fluxo

- Trabalhe em um ramo a partir da `develop` e junte nela com os testes verdes.
- Só a `main` recebe tag, depois de um fast-forward da `develop`. Nada de tag a partir da `develop`.
- Sem co-autor nem linha "Generated with" nos commits.
- Opções novas vêm desligadas por padrão e ganham teste e linha no README.
- O código não coleta nem envia uso.

## Estilo

Comentários só onde algo é difícil de entender, dizendo o porquê. Documente funções e classes com docstring.
