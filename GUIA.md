# Guia do Subir no Drive

## Instalar (uma vez em cada Mac)

1. Baixe **Subir-no-Drive-mac.zip** na [página de versões](../../releases/latest) e abra o zip
   (dois cliques).
2. Arraste **Subir no Drive.app** para a pasta **Aplicativos da sua pasta pessoal**
   (`~/Applications`). Se já existir um "Subir no Drive" lá (a versão 4), substitua.
   Não precisa de administrador.
3. Primeira abertura de cada versão: o app não tem assinatura da Apple, então o Mac bloqueia.
   Abra o **Terminal** e cole:

   ```
   xattr -dr com.apple.quarantine ~/Applications/"Subir no Drive.app"
   ```

4. Abra o app e arraste o ícone dele para o **Dock**. Se o ícone antigo (versão 4) estiver no Dock,
   tire o antigo e coloque o novo.

### Primeira vez neste Mac

- **Macs que já tinham a versão 4:** o app usa a mesma configuração (rclone, conexão e pasta inicial).
  Não pergunta nada.
- **Macs novos:** aparece a tela **Primeira vez neste Mac**:
  1. **Programa rclone:** o app procura sozinho (no setor fica em `~/Applications/rclone`). Se não achar,
     clique em **Escolher…** e aponte o arquivo `rclone`.
  2. **Conexão com o Google Drive:** escolha a da conta da instituição (o e-mail aparece ao lado).
  3. **Pasta inicial:** `Gravações IEC`.
  4. **Testar e salvar.**

  Se aparecer **"só tem permissão para LER"**, clique em **Corrigir permissão**: o Terminal abre com os
  comandos prontos. Aperte Enter em todas as perguntas, responda `y` em "Use web browser", e no navegador
  escolha a **conta da instituição** e clique em Permitir. Volte ao app e clique em **Conferir**.

## Usar

1. Arraste os vídeos editados para o **ícone no Dock** ou para a **janela** do app
   (ou clique em **Escolher vídeos…**).
2. Escolha a pasta: dois cliques para entrar numa pasta, a seta ou o caminho no topo para voltar.
   Ou **cole o link** da pasta do Drive no campo e aperte Enter.
   O normal é entrar em `<professor>/<AAAA MM DD>/Saída`.
3. Confira a caixa **Transcrever os vídeos** (vem marcada). Ela mostra para onde vai a transcrição:
   a pasta **Transcrições ao lado** da pasta escolhida (fora da Saída, para não ir para o servidor junto
   com os vídeos). A pasta é criada sozinha se não existir.
4. Clique em **Subir aqui** (ou **Subir em "…"** se uma pasta estiver selecionada).

### Enquanto envia

- Cada vídeo mostra duas barras: **Envio** (azul) e **Transcrição** (laranja). Os vídeos começam a subir na
  hora; a transcrição corre ao mesmo tempo e **não atrasa o envio**.
- Quando os vídeos terminam de subir, aparece **"Os vídeos já estão no Drive"**. Pode continuar trabalhando
  enquanto a transcrição termina.
- O Mac não dorme enquanto o app está enviando ou transcrevendo.

### Fechar antes de terminar

- **Vídeos ainda subindo:** o app pergunta. Fechar cancela o envio (o vídeo que estava subindo não fica no
  Drive; os que já subiram continuam lá).
- **Vídeos já no Drive, transcrição terminando:** o app pergunta. Fechar não muda nada nos vídeos; só a
  transcrição que faltava não sobe. Na revisão, o Revisor ouve esse vídeo sozinho, como sempre.

### Quando algo dá errado

- A tela final mostra o que deu certo e o que não deu, em português.
- **Tentar de novo** envia só o que falhou. O que já está no Drive não sobe de novo.
- Se a transcrição de um vídeo não sair (por exemplo, sem fala no áudio), o vídeo está certo no Drive; na
  revisão, o Revisor ouve sozinho.
- O registro do app fica em `~/Library/Application Support/SubirNoDrive/subir.log`. Se precisar de ajuda,
  mande um print da tela e esse arquivo.

## Perguntas

**Vídeo corrigido (rodada 2)?** Suba de novo para a mesma Saída. O vídeo é substituído e a transcrição é
feita de novo (o Revisor só usa a transcrição se a duração bater com a do vídeo).

**Posso desligar a transcrição?** Sim: desmarque a caixa antes de subir. Os vídeos sobem como antes.

**E as pastas?** Pode arrastar uma pasta: ela sobe inteira, mas sem transcrição dos vídeos de dentro.

**O Windows (outro campus) muda alguma coisa?** Não. Continua copiando para o servidor da PUC.
