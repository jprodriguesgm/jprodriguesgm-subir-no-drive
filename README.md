# Subir no Drive

App de Mac que envia os vídeos editados para o Google Drive da instituição **pela conta certa** (a do
rclone, não importa qual conta Google está aberta no navegador) e, **enquanto envia, transcreve cada
vídeo**. A transcrição sobe para a pasta `Transcrições` ao lado da pasta escolhida, e o
[Revisor de Vídeos](https://github.com/jprodriguesgm/revisor-de-videos) usa essa transcrição pronta em vez
de ouvir as falas de novo.

- **Baixar:** [Subir-no-Drive-mac.zip (versão oficial mais recente)](../../releases/latest/download/Subir-no-Drive-mac.zip)
- **Como instalar e usar:** [GUIA.md](GUIA.md)
- **Decisões e regras do projeto:** [PROJETO.md](PROJETO.md)
- **Licenças:** código sob GPL-3.0-or-later ([LICENSE](LICENSE)); programas que vão dentro do app em
  [LICENCAS-DE-TERCEIROS.md](LICENCAS-DE-TERCEIROS.md)

Mac com Apple Silicon (M1 ou mais novo), macOS 11 ou mais novo. Não precisa de administrador.

## Como é feito

| Parte | Arquivo |
|---|---|
| Janela (WebKit, sem barra do sistema) | `subir/mac.py` |
| Tela (HTML) | `subir/ui/index.html` |
| Pedidos da tela | `subir/app.py` |
| Envio e transcrição em paralelo | `subir/job.py` |
| rclone (pastas, link, envio com progresso) | `subir/rclone.py` |
| Transcrição (mesmo motor do Revisor) | `subir/fala.py` |
| Configuração (`env.sh` e `config.txt`, formato da versão 4) | `subir/config.py` |
| Montagem (GitHub Actions) | `.github/workflows/montar.yml`, `packaging/` |

Para desenvolver sem Mac: `python -m subir dev` abre a mesma tela no navegador, com um rclone de mentira
(`tools/fake_rclone.py`) e a transcrição simulada (`SUBIR_FAKE_FALA=1`). Testes: `python -m pytest tests`.
