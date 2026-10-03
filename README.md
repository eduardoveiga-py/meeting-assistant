# 🖥️ Meeting Assistant

![Windows 11](https://img.shields.io/badge/Windows-11-blue?style=flat-square&logo=windows)
![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?style=flat-square&logo=python)
![PySide6](https://img.shields.io/badge/PySide6-GUI-green?style=flat-square&logo=qt)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

O **Meeting Assistant** é um orquestrador open-source criado para simplificar e automatizar a operação de áudio e vídeo em Salões do Reino. Ele conecta e coordena **OBS Studio, JW Library, Zoom e WhatsApp**, permitindo que o operador foque na reunião, sem se preocupar com transições manuais complexas, roteamento de áudio ou gerenciamento de múltiplas janelas.

---


## 📸 Telas do Aplicativo

<p align="center">
  <img src="docs/screenshots/painel-principal.png" width="32%" alt="Painel Principal">
  <img src="docs/screenshots/configuracao.png" width="32%" alt="Ajustes">
  <img src="docs/screenshots/assistente.png" width="32%" alt="Assistente de Instalação">
</p>

---

## ✨ Principais Funcionalidades

* **🤖 Automação do JW Library e OBS:**
  O sensor de imagem identifica repouso e mídia, com calibração do Texto do Ano.
  O guardião atua somente com a automação ligada; respeita Zoom, mídia externa e transições.
* **🎥 Câmera virtual Windows 11:**
  A ponte nativa recebe o Program do OBS e entrega vídeo ao WhatsApp. A câmera virtual
  do OBS atende o Zoom. O áudio usa dispositivos virtuais separados do vídeo.
* **🎬 Mídia externa:**
  O operador escolhe a janela de um player ou navegador permitido. Uma captura
  exclusiva envia sua imagem ao OBS e ao salão, preservando a fonte do JWL.
  O retorno restaura a disposição anterior e verifica o JWL.
* **🎤 Microfone do operador no Zoom:**
  O painel mostra estado observado e solicita silenciar/ativar seu microfone.
  Controles coletivos e identidades ambíguas são recusados.
* **🔄 Atualizações e histórico:**
  O aviso oferece versões estáveis mais recentes. No app instalado, o instalador
  exige checksum, reunião encerrada e saída do processo atual antes de iniciar.
  Em execução Python, a atualização continua por Git e `scripts/run.ps1`.
  Restaurar uma versão anterior é uma escolha explícita no histórico; ajustes
  e coleção de cenas precisam de backup próprio.
* **🎮 Modo de Simulação:**
  Treine novos operadores em casa ou em notebooks comuns sem bagunçar as configurações oficiais ou precisar de dois monitores físicos.

---

## 🛠️ Arquitetura de Áudio e Vídeo

O fluxo de mídia automatizado reduz a carga cognitiva do operador. A rota padrão é:

Mesa e mídias selecionadas alimentam o monitoramento OBS → **CABLE Input**.
No perfil comum, Zoom e WhatsApp usam **CABLE Output** como microfone; nenhum
retorno dos aplicativos entra nesse mix. O perfil opcional com participantes do
Zoom no WhatsApp exige uma segunda entrada virtual e o plugin Audio Monitor.
Veja a [configuração dos dois perfis](docs/audio-routing.md).

O retorno físico da mesa precisa excluir o Zoom e as mídias capturadas separadamente.
Se esse retorno já contém tudo, o app não consegue separar os sinais depois de misturados.

---

## 🚀 Instalação (Windows 11)

**O instalador já inclui o Python embutido e todas as bibliotecas necessárias.**

1. Acesse a área de [Releases](../../releases) deste repositório.
2. Baixe o instalador da última versão (Ex: `MeetingAssistant-Setup-X.Y.Z.exe`).
3. Execute e siga as etapas da tela.
4. Abra o **Meeting Assistant** pelo menu Iniciar.
5. Na primeira abertura, configure as opções do OBS e selecione a Tela do Salão (Tela 2) na aba de Ajustes (⚙️).

### Pré-requisitos Externos:
* **Windows 11 x64** (Obrigatório para a câmera virtual Media Foundation)
* **OBS Studio** (com configuração de WebSocket ativada)
* **Zoom Desktop** e/se **WhatsApp (UWP)**
* **JW Library para Windows**
* **VB-CABLE** (Driver de áudio virtual, recomendado)

---

## 💻 Painel do Sistema (Operação)

O painel principal foi desenhado para uso em monitores de toque ou mouse, de forma extremamente enxuta:

| Botão | Ação |
|---|---|
| **▶ Iniciar Reunião** | Solicita OBS, Zoom, JWL e WhatsApp; verifica abertura e inicia câmera virtual. |
| **🔴 Encerrar** | Pausa automação/câmeras, solicita fechamento normal e informa confirmações pendentes. |
| **⚙️ Ajustes** | Configurações de Telas, Cenas do OBS, Atualizações, Diagnósticos e Rollback. |
| **🎬 Mídia Externa** | Seleciona janela, prepara captura própria no OBS e apresenta na tela do salão. |
| **📷 Câmera WhatsApp** | Inicia/Para o envio de vídeo do OBS para o aplicativo do WhatsApp. |
| **🎤 Mic Zoom** | Alterna entre "Mudo/Aberto" no Zoom em segundo plano. |

F1 mostra os atalhos disponíveis. Atalhos globais são opcionais e não substituem os atalhos do Windows indiscriminadamente.

---

## Correções em desenvolvimento

O código de `main` inclui as correções da revisão de 03/10/2026. Elas ainda precisam
de ensaio físico em Windows 11; o instalador v0.8.1 já publicado não contém este lote.
[Confira as alterações e o roteiro de testes](docs/review-fixes-2026-10-03.md).

A correção do **Mic Zoom** consulta o estado atual antes de alternar e informa
falhas do controle. [Roteiro de teste e diagnóstico](docs/zoom-microphone-control.md).

Para continuar testando pelo Python, na pasta do projeto:

```powershell
git pull --ff-only
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

O script usa Python 3.12, atualiza a `.venv` e verifica os componentes nativos
pré-compilados conforme o manifesto. Não exige MSBuild nem compilação local.
Os componentes da câmera e da ponte OBS não foram alterados neste lote.

## 👨‍💻 Para Desenvolvedores

Se deseja modificar ou rodar a partir do código fonte:

```powershell
git pull --ff-only
.\scripts\run.ps1
```

O script `.ps1` criará o ambiente virtual (`.venv`), instalará dependências via `pip` e cuidará dos binários e DLLs nativas em C++ responsáveis pela Virtual Camera.

**Dependências Principais:**
- `PySide6` (GUI)
- `pywinauto` e `pycaw` (Automação de Janelas e Áudio do Windows)
- `obsws-python` (Integração com OBS via WebSocket)

---

## ⚠️ Avisos e Isenção de Responsabilidade
O **Meeting Assistant** é um projeto independente e não-oficial. Não possui qualquer afiliação direta com JW Library, Zoom Video Communications ou OBS Project. Marcas e softwares pertencem aos seus respectivos criadores.

*Nota de Privacidade:* Logs gerados pela telemetria interna de diagnóstico são armazenados no `%APPDATA%` e desvinculados da operação real.
