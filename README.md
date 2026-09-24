<p align="center">
  <img src="src/meeting_assistant/resources/app_icon.svg" width="88" alt="Meeting Assistant">
</p>

<h1 align="center">Meeting Assistant</h1>

<p align="center"><strong>Operação integrada de JW Library, OBS Studio e Zoom para reuniões no Windows.</strong></p>

<p align="center">
  <img src="https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4?style=for-the-badge&logo=windows&logoColor=white" alt="Windows">
  <img src="https://img.shields.io/badge/Python-runtime%20incluído-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python runtime incluído">
  <img src="https://img.shields.io/badge/Release-0.5.0-22C55E?style=for-the-badge" alt="Release 0.5.0">
  <img src="https://img.shields.io/badge/Status-primeira%20release%20instalável-F59E0B?style=for-the-badge" alt="Primeira release instalável">
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
| 🎙️ Áudio | Preparação de fontes de microfone/aplicativos e rota OBS → VB-CABLE → Zoom. A configuração física continua explícita. |
| ⚙️ Assistente | Verifica o ambiente, ajuda a configurar o WebSocket e pode instalar OBS/Zoom usando WinGet com autorização. |
| 🧪 Telemetria | Diagnóstico estruturado, sanitizado e desacoplado da operação. |

### Diagnóstico e recuperação

O diagnóstico é local por padrão e não exige Git nem acesso à internet. Em Ajustes,
use **Exportar última sessão para revisão** para gerar um ZIP textual; screenshots,
configurações e histórico Git ficam fora desse arquivo. Revise os textos antes de compartilhar.

Sincronização automática é opcional e exige habilitar a opção específica, informar
um repositório e ter Git/autenticação disponíveis. Essa opção começa desativada também
na migração de configurações antigas. Confirme a privacidade do destino antes de ativá-la.
Screenshots, se habilitados separadamente, capturam todos os monitores e podem conter dados pessoais.

Configurações inválidas são recuperadas seletivamente e o arquivo original recebe
um backup local `settings.json.invalid-<identificador>.bak`. Esse backup pode conter
credenciais; não o inclua em um diagnóstico compartilhado. Falhas ao iniciar ou gravar
diagnóstico não impedem o uso da reunião.

Pesquisa e plano de conclusão: [comparação técnica de 24/09/2026](docs/comparative-review-2026-09-24.md).

### 🔒 Núcleo visual validado

O comportamento **JWL ↔ Zoom ↔ Salão** foi validado pelo operador em **21/09/2026**. Esse núcleo possui checkpoint e teste de integridade e não deve ser alterado para implementar recursos paralelos sem nova validação física.

---

## 📦 Instalação para quem nunca instalou Python

**Você não precisa instalar Python, PySide6, OBS WebSocket ou qualquer biblioteca Python.**

1. Abra a área de **Releases** do repositório.
2. Baixe `MeetingAssistant-Setup-0.5.0.exe`.
3. Execute o instalador e siga as etapas.
4. Abra o **Meeting Assistant** pelo menu Iniciar ou pelo atalho criado.
5. Na primeira abertura, use o **Assistente de instalação e configuração** para verificar o ambiente.

### Aplicativos externos necessários

O instalador não redistribui softwares de terceiros. Para a operação completa, instale:

- **OBS Studio**
- **Zoom para desktop**
- **JW Library para Windows**
- **VB-CABLE**, quando o áudio de mídia for enviado ao Zoom

O assistente pode ajudar a instalar OBS e Zoom por WinGet, com autorização explícita. O JW Library deve ser instalado pela fonte oficial. O VB-CABLE é um driver externo e deve ser instalado pelo fabricante.

📘 **Passo a passo:** [docs/installation.md](docs/installation.md)

---

## 🎧 Áudio para o Zoom

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
             Zoom
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
| F2 | Fundo / Texto do Ano |
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

O responsável confirmou áudio e câmera IP no equipamento atual em 24/09/2026. Para encerrar o aceite operacional da próxima versão:

1. executar e registrar os cenários de reinício de OBS/Zoom, reconexão de monitor e abertura durante vídeo;
2. conferir atualização e retorno de versão no equipamento habitual;
3. publicar a versão preparada após o aceite correspondente.

O [guia de recuperação](docs/recovery-and-updates.md) contém procedimentos e resultados esperados. O ensaio completo em Windows limpo está fora desta entrega por decisão do responsável. Atualizador automático e tutorial ilustrado são melhorias futuras; o procedimento atual de atualização é manual.

O [roadmap histórico](docs/roadmap-after-hall-validation.md) preserva o planejamento anterior; para o estado atual, use o registro de recuperação acima.

---

## ℹ️ Avisos

O Meeting Assistant é um projeto independente e não oficial do JW Library, Zoom ou OBS Studio. Nomes, marcas e aplicativos externos pertencem aos respectivos titulares.

Arquivos de configuração podem conter informações privadas. Não publique `%APPDATA%\\MeetingAssistant\\settings.json` ou sessões de telemetria que contenham dados operacionais sem revisão.

## Preparação da versão 0.5.1

A versão 0.5.1 está preparada no código; a versão publicada indicada acima continua sendo a 0.5.0 até uma nova release. Consulte o [guia rápido](docs/operator-guide.md) e a [matriz de recuperação e atualização](docs/recovery-and-updates.md). Áudio e câmera IP foram confirmados pelo responsável no equipamento atual em 24/09/2026.
