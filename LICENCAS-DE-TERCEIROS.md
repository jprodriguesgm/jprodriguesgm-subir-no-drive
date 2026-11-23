# Licenças de terceiros

O código do Subir no Drive é licenciado sob a **GPL-3.0-or-later** (arquivo [LICENSE](LICENSE)); parte dele
foi copiada do [Revisor de Vídeos](https://github.com/jprodriguesgm/revisor-de-videos), também GPL-3.0.
O app pronto (Releases) leva dentro os programas e dados abaixo, todos com licença livre e compatível com a
GPL-3.0. O rclone **não** vai dentro do app: o app usa o rclone que já está no Mac.

| Peça | Versão | Licença | Para que serve no app | Código-fonte |
|---|---|---|---|---|
| FFmpeg / FFprobe | 8.1.3 (montado do código) | GPL-2.0-or-later (montado com libx264) | ler a duração e o áudio dos vídeos | https://ffmpeg.org |
| x264 (libx264) | ramo `stable` | GPL-2.0-or-later | vai junto no FFmpeg (mesma montagem do Revisor) | https://code.videolan.org/videolan/x264 |
| whisper.cpp (ggml) | v1.9.5 | MIT | transcrever as falas, sem internet | https://github.com/ggml-org/whisper.cpp |
| Modelo `ggml-small-q5_1.bin` | — | MIT (pesos do Whisper, OpenAI) | modelo de fala | https://huggingface.co/ggerganov/whisper.cpp |
| Python | 3.12 | PSF License 2.0 | o app em si | https://www.python.org |
| NumPy | — | BSD-3-Clause | contas do áudio (pausas) | https://numpy.org |
| PyObjC | — | MIT | janela do Mac (AppKit e WebKit) | https://github.com/ronaldoussoren/pyobjc |
| PyInstaller (bootloader) | — | GPL-2.0-or-later com exceção do bootloader | empacotar o app | https://pyinstaller.org |

As versões exatas e a forma como cada programa é montado estão em
[packaging/build_deps.py](packaging/build_deps.py). A montagem é feita pelo GitHub Actions
([.github/workflows/montar.yml](.github/workflows/montar.yml)), com registro público de cada montagem.
