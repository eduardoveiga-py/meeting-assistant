<p align="center"><img src="src/meeting_assistant/resources/app_icon.svg" width="80" alt="Meeting Assistant"></p>

# Meeting Assistant

**Uma interface para operar JW Library, OBS Studio e Zoom nas reuniões.**

[![Verificações Windows](https://github.com/eduardoveiga-py/meeting-assistant/actions/workflows/ci.yml/badge.svg?branch=feature%2Fmeeting-launch-zoom-hall)](https://github.com/eduardoveiga-py/meeting-assistant/actions/workflows/ci.yml)
![Plataforma Windows](https://img.shields.io/badge/plataforma-Windows-0078D4)
![Em desenvolvimento](https://img.shields.io/badge/status-em_desenvolvimento-DAA520)

[Guia de uso](docs/operator-guide.md) · [Próximas entregas](docs/roadmap-after-hall-validation.md) · [Versão protegida](docs/validated-hall-contract.md) · [Soluções reaproveitáveis](docs/reuse-assessment.md)

## O que já funciona

| Recurso | Comportamento |
| --- | --- |
| Saída do Salão | Janela secundária nativa do JW Library; recuperação após Windows+D. |
| Zoom → Salão | Alterna a segunda tela entre JWL e participantes, mantendo as janelas abertas. |
| Automação de cenas | Texto do ano em repouso → Palco; mídia → Mídias; fim da mídia → Palco. |
| Controle do OBS | WebSocket, seleção de cenas, preview e diagnóstico de cenas ausentes. |
| Iniciar reunião | Abre/reaproveita programas e solicita entrada no Zoom pelo link configurado. |
| Operação | Ajustes persistentes, cena segura, observação de mídia e telemetria configurável. |

O operador validou a troca de telas em 21/09/2026. Esse núcleo tem checkpoint e teste de integridade. A validação em outros computadores ainda faz parte da entrega.

**A saída física do Salão e o vídeo enviado ao Zoom são independentes.** Mostrar participantes na segunda tela não deve reenviar a imagem deles pela câmera virtual. O preview atual vem do OBS e não comprova sozinho o que aparece no monitor do Salão.

## Instalação atual — desenvolvimento

Ainda não há um instalador final aprovado neste roteiro. O procedimento abaixo exige Windows x64, Python **3.12 estável**, Git e acesso ao repositório. O app é apresentado como Meeting Assistant 3.0; a versão técnica atual do pacote é 0.4.2.

```powershell
git clone --branch feature/meeting-launch-zoom-hall https://github.com/eduardoveiga-py/meeting-assistant.git
cd meeting-assistant
.\scripts\setup-dev.ps1
.\scripts\run-dev.ps1
```

O script cria o ambiente virtual, instala dependências e executa testes. Se o PowerShell bloquear scripts, siga a política do computador antes de executá-los.

Para atualizar uma instalação de desenvolvimento sem alterações locais, feche apenas o Meeting Assistant:

```powershell
git pull --ff-only
.\scripts\setup-dev.ps1
.\scripts\run-dev.ps1
```

OBS Studio, Zoom e JW Library são aplicativos externos. Instale-os pelas fontes oficiais e siga o [guia](docs/operator-guide.md). A primeira configuração das fontes OBS ainda é manual.

## Preparação rápida

1. Configure o Windows para estender a área de trabalho e a saída secundária do JWL para o monitor do Salão.
2. Habilite o servidor WebSocket do OBS e informe host, porta e senha em **Ajustes**.
3. Mapeie **Fundo / Texto do Ano**, **Palco** e **Mídia** para as cenas existentes.
4. No Zoom, habilite dois monitores antes de entrar na reunião. Selecione **OBS Virtual Camera** como câmera e inicie a câmera virtual no OBS.
5. Clique em **Verificar** e teste a alternância antes da reunião.

## Câmera IP e preparação do OBS — implementado, validação física pendente

Em **Ajustes → Câmera IP — Palco**, informe IP, usuário e senha. O perfil inicial usa IP 10.0.0.40, RTSP 554, canal 1/fluxo principal. Usuário e senha começam vazios. **Salvar** apenas armazena os dados; **Salvar e preparar cenas / câmera no OBS** aplica a configuração com confirmação.

A preparação padroniza **Texto do Ano**, **Palco** e **Mídias**. Cenas mapeadas com nomes antigos são renomeadas quando não há conflito; fontes existentes são preservadas. A câmera recebe fonte de mídia própria e áudio silenciado. Isso não configura automaticamente as fontes de Texto do Ano e Mídias nem comprova recepção da câmera.

Quando aberto pelo Meeting Assistant, o OBS recebe os parâmetros para iniciar na bandeja com câmera virtual. Em Ajustes, há uma opção para criar o atalho de inicialização no login do Windows. OBS já aberto não é reiniciado. [Detalhes e limites](docs/obs-ip-camera.md).

## Texto do Ano e fontes OBS — pronto para teste físico

Em **Ajustes → Texto do Ano, captura JWL e câmera virtual…**, capture o JWL visível na tela selecionada, confira prévia/ano e salve. A foto de apresentação não modifica a referência do detector. O app avisa sobre foto ausente, inválida ou de outro ano.

A mesma tela prepara a captura da janela JWL em Mídias e verifica fontes/câmera virtual. A identificação precisa ser inequívoca; nunca é substituída por captura de monitor. **Iniciar reunião** solicita e confirma a câmera virtual, inclusive quando o OBS já está aberto.

[Procedimento de teste](docs/yeartext-and-obs.md) · [Histórico de alterações](CHANGELOG.md)

## Em preparação

- Validar fisicamente a nova captura anual e as fontes do OBS no equipamento do Salão.
- Atualizador com tela própria, consulta de Releases na inicialização e preservação dos dados.
- Áudio de mídia e microfones para o Zoom sem reenviar o retorno remoto.
- Ferramentas avançadas em Ajustes, guia ilustrado e instalador independente de Python instalado.

Áudio integrado, atualizador, reorganização das ferramentas, tutorial ilustrado e instalador **ainda estão pendentes**. Consulte critérios e prioridades no [roteiro](docs/roadmap-after-hall-validation.md).

## Desenvolvimento e qualidade

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
```

O CI executa Ruff e Pytest no Windows. `core/` guarda estado, `services/` integra aplicativos e `ui/` contém a interface. Leia [AGENTS.md](AGENTS.md) antes de alterar o núcleo validado.

## Distribuição futura

A publicação do código e do instalador ocorrerá quando o responsável autorizar tornar o projeto público. Antes disso: testes em Windows sem Python, revisão das licenças das dependências, remoção de dados locais/segredos e Releases com versão, notas e checksum. Links privados de reunião, senhas, imagens locais e telemetria não devem integrar o pacote público.

Projeto independente, não oficial de JW Library, Zoom ou OBS.


