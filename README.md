<p align="center">
  <img src="src/meeting_assistant/resources/app_icon.svg" width="88" alt="Meeting Assistant">
</p>

<h1 align="center">Meeting Assistant</h1>

<p align="center"><strong>Operação integrada de JW Library, OBS Studio e Zoom para reuniões no Windows.</strong></p>

<p align="center">
  <img src="https://img.shields.io/badge/Windows-11%20x64-0078D4?style=for-the-badge&logo=windows&logoColor=white" alt="Windows">
  <img src="https://img.shields.io/badge/Python-runtime%20incluído-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python runtime incluído">
  <img src="https://img.shields.io/badge/Release-0.6.0--dev1-22C55E?style=for-the-badge" alt="Release 0.7.0">
  <img src="https://img.shields.io/badge/Status-build%20Windows%2011%20em%20validação-F59E0B?style=for-the-badge" alt="Build Windows 11 em validação">
</p>

<p align="center">
  <a href="../../releases">📦 Releases</a> ·
  <a href="docs/installation.md">🚀 Instalação</a> ·
  <a href="docs/operator-guide.md">🎛️ Guia do operador</a> ·
  <a href="docs/roadmap-after-hall-validation.md">🧭 Próximos passos</a>
</p>

---

## ✨ O que esta versão entrega

| Área | O que já está no aplicativo |
|---|---|
| 🖥️ Salão | Uso da janela secundária do JW Library e recuperação após alterações do shell/área de trabalho. |
| 🔵 Zoom → Salão | Mostra os participantes no segundo monitor sem trocar o programa principal do OBS. |
| 🎬 Automação | Texto do ano em repouso → **Palco**; mídia → **Mídias**; fim da mídia → **Palco**. |
| 🎚️ OBS | Controle por WebSocket, mapeamento de cenas, preview e diagnóstico. |
| 🚀 Iniciar reunião | Detecta/abre OBS, JW Library e Zoom e pode abrir diretamente um link normal de convite do Zoom. |
| 🎙️ Áudio | Preparação de fontes de microfone/aplicativos e rota OBS → VB-CABLE → Zoom + WhatsApp, com retorno do WhatsApp silenciado por padrão. |
| 📹 Câmera | Câmera virtual nativa Windows 11 iniciada automaticamente após a conexão do OBS, com controle na tela principal. |
| ⚙️ Assistente | Verifica o ambiente, ajuda a configurar o WebSocket e pode instalar OBS/Zoom usando WinGet com autorização. |
| 🧪 Telemetria | Diagnóstico estruturado, sanitizado e desacoplado da operação. |

### 🔒 Núcleo visual validado

O comportamento **JWL ↔ Zoom ↔ Salão** foi validado pelo operador em **21/09/2026**. Esse núcleo possui checkpoint e teste de integridade e não deve ser alterado para implementar recursos paralelos sem nova validação física.

---

## 📦 Distribuição final planejada para quem não tem Python

**O instalador final incluirá Python e as bibliotecas. Durante os testes atuais,
use o código Python conforme o procedimento abaixo. O instalador ainda precisa
da validação final; esta seção descreve a distribuição planejada.**

1. Abra a área de **Releases** do repositório.
2. Baixe `MeetingAssistant-Setup-0.7.0.exe`.
3. Execute o instalador e siga as etapas.
4. Abra o **Meeting Assistant** pelo menu Iniciar ou pelo atalho criado.
5. Na primeira abertura, use o **Assistente de instalação e configuração** para verificar o ambiente.

### Aplicativos externos necessários

O instalador inclui o runtime Microsoft Visual C++ e as DLLs nativas. Para a operação completa, instale:

- **OBS Studio**
- **Zoom para desktop**
- **JW Library para Windows**
- **VB-CABLE**, quando o áudio de mídia for enviado ao Zoom
- **WhatsApp para desktop**, quando usar a câmera Meeting Assistant

O assistente pode ajudar a instalar OBS e Zoom por WinGet, com autorização explícita. O JW Library deve ser instalado pela fonte oficial. O VB-CABLE é um driver externo e deve ser instalado pelo fabricante.

📘 **Passo a passo:** [docs/installation.md](docs/installation.md)

### Executar o codigo Python durante o desenvolvimento

Atualize a pasta e execute:

```powershell
git pull --ff-only
.\scripts\run.ps1
```

O script cria/reutiliza `.venv`, atualiza as dependencias quando `pyproject.toml`
muda e executa `python -m meeting_assistant.main` a partir do `src` desta pasta.
Ele reutiliza a camera/ponte ja instaladas; se faltarem, baixa somente o pacote
nativo. Use `-Refresh` quando precisar atualizar os componentes nativos.

A camera tem DLLs e pequenos executaveis C++ auxiliares; o aplicativo principal
continua em Python. O executavel e o instalador finais ficam para a distribuicao.
Veja [o procedimento completo](docs/installation.md).

---

## 🎧 Áudio para Zoom e WhatsApp

O caminho usado nesta release é:

```text
JW Library / VLC / Chrome / Edge
              ↓
      Captura de áudio no OBS
              ↓
        Mixer / monitoramento
              ↓
          CABLE Input
              ↓
         CABLE Output
              ↓
        Zoom + WhatsApp
```

No OBS, o dispositivo de monitoramento deve ser **CABLE Input (VB-Audio Virtual Cable)**. No Zoom, a entrada deve ser **CABLE Output**.

A primeira validação feita nesta etapa confirmou que o áudio do **JW Library pode ser enviado pelo OBS usando VB-CABLE**. O aplicativo ainda trata essa configuração como uma etapa explícita do operador, porque a entrada física, mix-minus, retorno do Zoom e teste de escuta precisam ser confirmados no computador real.

Também evite capturar a mesma mídia duas vezes — por exemplo, pela captura do aplicativo e pelo `Desktop Audio` — porque isso pode produzir duplicação.

📘 **Procedimento de áudio:** [docs/test-audio-shortcuts.md](docs/test-audio-shortcuts.md)

---

## 🧭 Primeiro uso

Depois de instalar:

```text
1. Abrir Meeting Assistant
2. Ajustes → salvar OBS e cenas
3. Escolher a tela do Salão
4. Verificar ambiente
5. Preparar fontes do OBS
6. Configurar CABLE Input / CABLE Output
7. Testar voz + JWL + VLC/navegador
8. Fazer o ciclo Zoom → Salão → JWL
```

**Não faça o primeiro teste durante uma reunião pública.** Faça o ensaio com outro dispositivo conectado ao Zoom, preferencialmente com fones.

---

## 🧰 Atalhos da operação

| Tecla | Ação |
|---|---|
| F1 | Ajuda |
| F2 | Texto do Ano |
| F3 | Palco |
| F4 | Mídia |
| F5 | Zoom → Salão / voltar ao JWL |
| F6 | Ativar / pausar automação |
| F7 | Cena segura → Palco |
| F8 | Iniciar reunião |
| F9 | Verificar |
| F10 | Ajustes |

Os atalhos são locais à janela do Meeting Assistant e não funcionam como atalhos globais do Windows.

---

## 🏗️ Desenvolvimento

O projeto usa Python 3.12 durante o desenvolvimento, mas a distribuição oficial é empacotada para Windows pelo GitHub Actions.

```text
src/meeting_assistant/
├── core/       estado e coordenação
├── services/   OBS, JWL, Zoom, áudio, diagnóstico e configuração
├── ui/         interface PySide6
└── resources/  ícones e recursos
```

Para desenvolvimento:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
pytest
ruff check .
```

O build de distribuição usa **PyInstaller + Inno Setup** no Windows. O roteiro está em [packaging/README.md](packaging/README.md).

---

## 🧭 O que vem depois

A primeira release instalável não significa que todas as rotinas físicas estejam certificadas. As próximas prioridades são:

1. ensaio do instalador em uma máquina Windows limpa;
2. ensaio completo de áudio e confirmação de estéreo no Zoom;
3. substituir a captura JWL por método alternativo quando uma máquina não fornecer áudio pela captura de processo;
4. terminar a configuração física da câmera IP;
5. criar atualizador seguro entre releases, preservando configurações;
6. concluir tutorial ilustrado e matriz de aceitação para operação no Salão.

Veja o [roadmap detalhado](docs/roadmap-after-hall-validation.md).

---

## ℹ️ Avisos

O Meeting Assistant é um projeto independente e não oficial do JW Library, Zoom ou OBS Studio. Nomes, marcas e aplicativos externos pertencem aos respectivos titulares.

Arquivos de configuração podem conter informações privadas. Não publique `%APPDATA%\\MeetingAssistant\\settings.json` ou sessões de telemetria que contenham dados operacionais sem revisão.


## Desenvolvimento atual — Windows 11 obrigatório

O requisito atual é **Windows 11 x64, build 22000 ou superior**. A versão em desenvolvimento
usa uma câmera própria Media Foundation para receber **Program do OBS**, sem NDI.
A prévia principal e a da câmera usam vídeo contínuo NV12, com alvo de 30 fps.

As tentativas Windows 10 (DirectShow Compat e driver experimental) foram retiradas.
A release 0.5.0 acima é anterior a esta mudança. Use o pacote do workflow
**Windows 11 video**, que inclui app portátil com Python/bibliotecas e componentes nativos.
A câmera ainda depende de validação física no WhatsApp antes de ser considerada aprovada.

- [Instalação e testes no Windows 11](docs/test-virtual-camera.md)
- [Arquitetura modular e decisão técnica](docs/windows11-video-architecture.md)
