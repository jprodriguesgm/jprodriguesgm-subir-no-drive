# Projeto — Subir no Drive (versão 5: app montado pelo GitHub, com transcrição)

## Origem

A versão 4 era um instalador `.command` que criava o app no Mac (AppleScript + janela WebKit). Resolvia o
envio pela conta errada: os Macs do setor têm 3 contas Google abertas e a equipe subia na conta errada; o
rclone envia sempre pela conta guardada na configuração dele.

A versão 5 (pedido do JP, 23/11/2026) vira um `.app` montado pelo GitHub Actions que, além de subir,
**transcreve cada vídeo enquanto envia** e sobe a transcrição, para o Revisor de Vídeos não precisar ouvir
as falas de novo.

## Decisões do JP (23/11/2026)

1. Usado nos Macs do setor: Mac Studio M1 (editores), Mac mini M4, Mac do trabalho M1 Max com
   **macOS 13.1, sem administrador** → app para Apple Silicon, macOS 11 ou mais novo, nada instalado no
   sistema, dados na pasta do usuário.
2. **Visual igual ao da versão 4** (janela própria cinza escuro, cantos arredondados, borda branca fina,
   sombra azul clara, barra de progresso dentro do app, link colável, caminho em "migalhas", tela final com
   "Abrir no Drive" / "Tentar de novo", mensagens em português). Telas aprovadas antes de programar.
3. **Acesso próprio do Google Cloud para o rclone: fica para outro dia.** Hoje o rclone usa o acesso
   compartilhado, que o Google avisou que vai parar em 2026; quando cair, param o envio e o "Baixar do
   Drive" do Revisor.
4. Destino que não é Saída: a transcrição vai para a pasta **Transcrições ao lado** da pasta escolhida
   (mesma regra da Saída).
5. A caixa **Transcrever os vídeos** vem marcada e o editor pode desmarcar.

## Regras

- A transcrição **nunca atrasa o envio**: o vídeo começa a subir na hora; a transcrição roda em paralelo; o
  `.transcricao.json` sobe quando a transcrição fica pronta **e** o vídeo já subiu.
- Fechar o app antes do fim: os vídeos já enviados ficam; só falta a transcrição (o Revisor ouve sozinho).
- Organização no Drive: `<pasta das gravações>/<código + professor>/<AAAA MM DD>/Saída` (vídeos) e
  `.../<AAAA MM DD>/Transcrições` (fora da Saída, para não ir para o servidor/NAS junto com os vídeos).
  Usa a pasta "Transcrições" que já existir (com ou sem acento); se não existir, cria "Transcrições".
- Link colado: o app procura a pasta dentro da pasta inicial (até 4 níveis) para saber o caminho e a pasta
  ao lado. Se a pasta do link estiver fora da pasta inicial, sobe para ela, mas sem transcrição (não dá para
  saber qual pasta fica ao lado).
- Cada envio (rodada 2 também) gera a transcrição de novo: vídeo corrigido = outra duração = o Revisor
  ignoraria a transcrição antiga.
- Editores do Windows (outro campus) não mudam nada (copiam para o servidor da PUC).

## Formato da transcrição (o Revisor já lê; não mudar)

`"<nome do vídeo sem extensão>.transcricao.json"`, UTF-8 — ver `revisor/transcricao.py` no Revisor:

```json
{"formato": "revisor-transcricao", "versao": 1,
 "video": {"arquivo": "01 Aula.mp4", "duracao": 1002.37},
 "motor": {"programa": "whisper.cpp", "modelo": "ggml-small-q5_1.bin"},
 "aproximada": false, "criado": "2026-11-23 15:20:00",
 "words": [[inicio, fim, "palavra", prob], ...],
 "segments": [[inicio, fim, "frase"], ...]}
```

Tempos em segundos do vídeo inteiro. `duracao` é a do arquivo enviado (o Revisor só usa se bater ±0,5 s).
O app grava também `"segundos"` (tempo da transcrição) e `motor.onde` (Metal/CPU); o Revisor ignora.

## Motor (igual ao do Revisor)

- whisper.cpp (`whisper-cli`, Metal) + modelo `ggml-small-q5_1.bin`, em português, com o **mesmo prompt
  inicial "ao pé da letra"** e as mesmas opções (`-mc 0 -bs 1 -bo 1 -sns -dtw small -ojf`).
- Áudio em WAV 16 kHz mono (FFmpeg); pedaços de ~120 s cortados na pausa mais longa até 20 s antes do alvo;
  tokens juntados em palavras com o mesmo código (`words_from_whisper_json`).
- FFmpeg, whisper-cli e o modelo vão dentro do app, montados pelo GitHub Actions com as **mesmas versões** do
  Revisor (`packaging/build_deps.py`, copiado do Revisor sem o Tesseract).
- Diferença: o Revisor transcreve só o trecho entre as vinhetas; aqui é o vídeo inteiro (o Revisor filtra o
  trecho sozinho). Por isso os pedaços não caem exatamente nos mesmos pontos e uma ou outra palavra pode
  sair diferente da que o Revisor ouviria.
- Não usar o comando `transcribe` (mlx-whisper) do Mac do JP: o motor precisa ser o do Revisor.

## Configuração (compatível com a versão 4 e com o Revisor 1.2.0)

`~/Library/Application Support/SubirNoDrive/`:

- `env.sh`: `export PATH="<pasta do rclone>:$PATH"` e, se preciso, `export RCLONE_CONFIG="..."`;
- `config.txt`: 1ª linha = conexão do rclone (`drive`), 2ª = pasta inicial (`Gravações IEC`), 3ª = e-mail.

O Revisor 1.2.0 lê esses dois arquivos no "Baixar do Drive": **manter lugar e formato** (ou ajustar o
Revisor junto). Os outros arquivos que a versão 4 deixou nessa pasta (`upload.sh`, `ui.html`…) não são mais
usados e podem ficar.

## Distribuição

- GitHub Actions (`montar.yml`) monta o `.app` num Mac arm64, roda os testes (incluindo uma transcrição de
  verdade com voz do Mac), um teste de ponta a ponta com a janela (Drive de mentira + transcrição de
  verdade, com fotos da janela) e publica em Releases.
- "Versão oficial" vazia → "Montagem N (teste)" (pré-lançamento). Preenchida → versão oficial, link
  `releases/latest`. O JP testa a versão de teste e autoriza; a oficial sai no mesmo commit testado.
- Quando a montagem falha por falta de máquina Mac no GitHub, tentar de novo 5 minutos depois.
- Sem assinatura da Apple: primeira abertura de cada versão pede
  `xattr -dr com.apple.quarantine ~/Applications/"Subir no Drive.app"`.
- Nada de senha, conta, e-mail ou nome real de professor no repositório (o acesso ao Google fica no rclone
  de cada Mac).

## Projetos ligados

- **Revisor de Vídeos** (`jprodriguesgm/revisor-de-videos`): lê a transcrição pronta; tem "Baixar do Drive"
  opcional e "Adicionar transcrição manualmente".
- **Montador** (`jprodriguesgm/montador`): monta as sequências no Premiere; usa transcrição do bruto (outra
  coisa).
