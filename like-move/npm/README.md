# like-move

Instala e abre o [like-move](https://allansantos-dv.github.io/like-move/) com um comando, no Windows 10 ou 11, sem administrador:

```
npx like-move
```

O like-move mantém o Windows sem bloquear por inatividade, só quando você quer e só nas redes em que você confia. Não simula mouse nem teclado.

O comando baixa `like-move-win64.zip` da [release do GitHub](https://github.com/AllanSantos-DV/like-move/releases) da mesma versão deste pacote, confere o sha256 com o que veio dentro do pacote (nada é instalado se não bater), extrai em `%LOCALAPPDATA%\Programs\like-move\like-move-<versão>` e abre o app. O ícone aparece na bandeja do sistema.

O Home Awake (scripts em PowerShell que mantêm a tela acordada só no Wi-Fi de casa cadastrado):

```
npx like-move home-awake
```

Instala em `%LOCALAPPDATA%\Programs\like-move\home-awake` e roda o passo 1, o diagnóstico (somente leitura). Os passos seguintes estão no `LEIA-ME.txt` da pasta.

| Opção | O que faz |
|---|---|
| `--dir <pasta>` | instala em outra pasta |
| `--no-start` | só instala, não abre |

Requer Node.js 20 ou mais novo. Sem Node, baixe o zip direto da [página de releases](https://github.com/AllanSantos-DV/like-move/releases/latest).

Licença MIT.
