# Histórico de alterações

## Não lançado — Ajustes unificados e manutenção do OBS — 07/10/2026

- Uma janela por categorias: Reunião e janelas, OBS e vídeo, Áudio,
  Instalação e plugins e Diagnóstico. Foto, fontes e câmera ficam na categoria
  de vídeo; filtros/atraso ficam recolhidos na configuração de envio de áudio.
- Botão Volumes no painel abre diretamente os ganhos, sem acrescentar linha
  ao painel. Ganho de −30 a +18 dB; aplicação confirmada, independente da rota.
- Verificação OBS somente de leitura e conclusão incremental de cenas,
  fontes e vínculos ausentes. Preserva mapeamentos, fontes pessoais, fontes
  desativadas e envio existente; conflitos/pendências não são sobrescritos.
- Reparar estrutura de áudio não silencia mais fontes existentes. Novas fontes
  começam silenciadas, com seleção e ativação explícitas.
- Instalação explícita dos plugins na mesma janela. Audio Monitor usa ZIP
  oficial 0.10.1, SHA-256, backup e verificação posterior; JWL/câmera usam os
  componentes prontos do fluxo Python, sem compilação.
- Salvamento geral parte dos ajustes atuais, preservando ganhos já confirmados.
  OBS só é reconfigurado quando sua conexão muda. Avisos para edições/foto pendentes.
- Regressões Qt/OBS simulado incluem repetição, falhas parciais, preservação de
  envio, cliques dos botões e layouts em 100%, 125%, 150% e 200%.

Nenhuma mudança em DLLs, versão ou instalador. O ensaio físico desta organização
é separado do aceite histórico da captura JWL. [Mapa e testes](docs/settings-workspace.md).

## Não lançado — captura JWL por HWND e registro de aceite — 07/10/2026

- Fonte independente **Meeting Assistant - JWL (HWND)** distingue a saída
  secundária mesmo com títulos duplicados/vazios. Reutiliza Windows Graphics
  Capture do OBS; não captura monitor nem áudio.
- Vínculo valida identidade/geração, relação UWP e monitor. Migração preserva
  fontes; perda de alvo não procura outra janela pelo título.
- DLL pronta no componente `jwl-capture-v1.1`, download e hashes fixados pelo
  fluxo Python. Requer Windows 11 x64, OBS 31.0.3+ e Direct3D 11.
- Operador confirmou funcionamento após atualizar em 07/10/2026. Aceite
  limitado ao uso relatado; matriz de reinícios/monitor permanece por cenário.
- Registrados 31 incidentes, soluções e aprendizados em
  [incident-history.md](docs/incident-history.md), complementando o registro de decisões.
- Guias corrigidos para captura HWND, guardião condicionado à automação,
  separação de foto/calibração e atualização Git que preserva trabalho local.

O lote de documentação não altera código, DLLs, versão ou instalador. O
instalador já publicado não contém a nova captura; desenvolvimento usa Git/Python.

## Não lançado — configuração de áudio simplificada — 03/10/2026

- Corrigida enumeração de cabos virtuais: estado Enum do pycaw era comparado com
  inteiro, descartando dispositivos ativos da lista.
- Tela separada em Envio, Volumes e Ajuda; aplicativos extras ficam recolhidos.
- Abertura e Atualizar lista consultam o OBS sem silenciar o envio existente.
- Ganho de uma fonte pode ser salvo separadamente, com leitura de confirmação e
  restauração em falha, preservando dispositivos, mute e roteamento.
- Ativar envio explica e foca campos pendentes; segundo cabo permanece obrigatório
  para enviar participantes Zoom ao WhatsApp sem retorno ao próprio Zoom.
- Regressões incluem dispositivos Enum, cliques Qt, dois perfis, filtros e layout.
  Áudio físico e escuta remota desta revisão ainda exigem teste do operador.

## 0.6.0 — em avaliação

- Checkpoint da release estável 0.5.1 antes das mudanças.
- Contraste de abas e fechamento unificado do assistente; formulário incorporado não modal.
- Preview 480×270 independente dos comandos, até 20 FPS e descarte de quadros atrasados.
- Texto do Ano substitui Fundo; painel separa preview OBS de recepção remota.
- Contingência verifica a fonte e usa Texto do Ano diante de falha ou estado inconclusivo.
- Câmeras de rede, USB/captura e fontes existentes vinculadas a Palco.
- Controle do próprio microfone Zoom por acessibilidade, com confirmação de estado.
- Painel de preparação, recuperação, medidores, passagem de operador e encerramento assistido.
- Perfis sem credenciais, consulta de versões, treinamento isolado e atalhos globais opcionais.
- Pesquisa de download por idioma com importação assistida no JWL, sem player próprio.
- Novas integrações aguardam aceite físico; núcleo protegido permanece intacto.

## 0.5.1 — publicada em 24/09/2026

- Pré-verificação separa instalação, conexão, configuração e confirmação do operador.
- Falhas parciais de consulta preservam resultados obtidos; erros não expõem credenciais.
- Guia curto de operação, matriz de recuperação e atualização/retorno de versão.
- Áudio e câmera IP no equipamento atual confirmados pelo responsável em 24/09/2026.

- Diagnóstico local por padrão, sincronização opcional e exportação textual para revisão.
- Falhas de disco no diagnóstico isoladas da operação e fila de eventos limitada.
- Recuperação de configurações inválidas com preservação do original e aviso ao operador.
- Empacotamento em pasta consistente, metadados de versão e teste do executável no CI/release.
- Pesquisa comparativa e critérios objetivos para concluir a versão operacional.
- Núcleo validado JWL ↔ Zoom ↔ Salão e seus fingerprints preservados.
## Não lançado — áudio Zoom/WhatsApp e câmera na tela principal — 01/10/2026

- Inicializacao verifica Python 3.12 estavel x64 antes do pip; se `.venv` for
  incompativel, preserva backup e recria com 3.12. Confirma o interpretador base
  antes de alterar o ambiente existente. Mesma verificacao no setup de desenvolvimento.

- Corrigida restricao impossivel de versao pycaw no Windows; dependencia fixada
  em 20240210, com as interfaces de sessao usadas pelo controle de audio.

- Mix único do OBS para Zoom e WhatsApp via VB-CABLE, preservando o nome compatível
  `Meeting Assistant - Áudio Zoom`.
- Botão de retorno do WhatsApp na tela principal, silenciado por padrão e controlado
  por sessão individual do Windows Core Audio.
- Câmera virtual nativa do Windows 11 integrada à tela principal, com tentativa de
  inicialização automática depois da conexão do OBS.
- Botão F2 renomeado para **Texto do Ano**; a câmera deixou de ser uma ferramenta
  escondida em Ajustes.
- Pacote PyInstaller preparado para incluir `pycaw` no executável Windows.
- `scripts/run.ps1` executa o codigo Python atualizado da pasta `src`, prepara
  `.venv` e atualiza dependencias quando necessario; nao abre um app congelado em cache.
- Download/instalacao nativa isolada em `ensure-video-native.ps1`; reutiliza camera
  instalada e permite atualizar DLLs/host com `-Refresh` ou fornecer pacote local.
- Workflow de video prepara apenas dependencias C++ em `native-latest`; a geracao
  do executavel/instalador principal permanece reservada para a distribuicao final.
- Suíte automatizada: 233 testes aprovados; os novos controles de audio/interface
  aguardam o ensaio fisico desta atualizacao.

## Não lançado — Windows 11 e vídeo revisão 3 — 30/09/2026

- Windows 11 x64 passa a ser requisito do app e do instalador.
- Retiradas as alternativas DirectShow Compat, NDI e driver experimental Windows 10.
- Câmera nativa Media Foundation recebe Program do OBS, com identidade própria.
- Prévia contínua NV12 na tela principal e nos ajustes; sem screenshots JPEG ou
  conversão QImage/QPixmap por quadro. Canais independentes para prévia e câmera.
- Uma conexão persistente compartilhada entre as prévias; descarte de quadros atrasados.
- Câmera permanece ativa ao fechar ajustes, para permitir operar cenas na tela principal.
- Retomada após reinício OBS, desligamento explícito e diagnóstico revisão 3.
- Pacote de desenvolvimento inclui app portátil com Python e bibliotecas.
- Núcleo congelado JWL/Zoom preservado. Compatibilidade WhatsApp e fluidez no hardware
  aguardam confirmação do operador; compilação não substitui esse ensaio.

As entradas históricas abaixo descrevem tentativas anteriores, algumas já removidas.

## Não lançado — câmera de compatibilidade, 27/09/2026

- Módulo DirectShow separado para Windows 10 2004+/11 x64, identidade Meeting Assistant Compat.
- Mesma ponte Program OBS; saída NV12/I420/YUY2 720p30 e preto sem envio autorizado.
- Seleção Automático/Moderno/Compatibilidade na tela experimental; um consumidor por vez.
- Instalar, verificar e remover Compat separadamente, com SHA256 e verificador COM.
- Testes de formatos, ciclo de vida e controles; recepção WhatsApp depende de ensaio físico.
- Fontes correspondentes e licença libdshowcapture incluídas no pacote.

## Não lançado — instalador de vídeo / PowerShell 5.1, 27/09/2026

- Corrigida enumeração do manifesto JSON que podia causar falso erro de SHA256 no Windows PowerShell 5.1.
- Modo `-VerifyOnly` verifica integridade sem instalar nem exigir administrador.
- Build verifica pacote válido e rejeição de corrupção, duplicidade e arquivos ausentes em PowerShell 5.1 e 7.

## Não lançado — fluidez e diagnóstico de vídeo, 27/09/2026

- Cadência da ponte baseada no timestamp OBS; elimina limitador de 32 ms em relógio de baixa resolução.
- Prévia com alvo de 30 fps, conversão fora da interface, sem fila de quadros atrasados.
- Diagnóstico diferencia FPS da ponte e da prévia, contabiliza erros e limpa estado obsoleto.
- Parada durante leitura é enfileirada; reconexão não inicia o envio automaticamente.
- Provedor Windows 11 usa cadência monotônica; requer validação física no WhatsApp.
- Pacote inclui revisão/commit e verifica hashes antes de instalar os binários.
- Testes nativos de 24/29,97/30/60 fps, pausa e reinício do timestamp.
- Operador validou troca de cenas e parar/reiniciar na versão anterior; fluidez corrigida aguardando reteste.

## Não lançado — câmera própria, 27/09/2026

- Plugin separado de saída Program OBS em NV12 720p e transporte local com timeout.
- Tela experimental com prévia, diagnóstico copiável e bloqueio da câmera própria no Windows 10.
- Provedor Windows 11 baseado no exemplo MIT Microsoft, com CLSID próprio e câmera de sessão.
- Build nativo reproduzível em commits fixos; scripts explícitos de instalação e remoção.
- Núcleo de telas preservado; ensaio Windows 11/WhatsApp e distribuição final ainda pendentes.

## 0.5.0 — primeira release instalável — 21/09/2026

### Entrega

- Primeira distribuição Windows empacotada, com runtime Python e bibliotecas Python incluídos.
- Instalador por usuário usando Inno Setup.
- Build oficial no GitHub Actions com PyInstaller e checksum SHA-256.
- README reorganizado com visão geral, instalação e operação para novos usuários.
- Guia dedicado de instalação sem Python.

### Áudio

- Preparação de fontes de microfone e captura por aplicativo no OBS.
- Rota operacional documentada: OBS → monitoramento → VB-CABLE → Zoom.
- Validação manual registrada: JWL → OBS → VB-CABLE → Zoom funciona no ambiente de teste.
- Captura por processo continua com limitações específicas por aplicativo; JWL pode exigir método alternativo em algumas máquinas.

### Núcleo preservado

- Mantida a referência validada de 21/09/2026 para JWL ↔ Zoom ↔ Salão.
- Mantido o checkpoint original e o teste de integridade do núcleo visual.

### Limitações conhecidas

- OBS Studio, Zoom, JW Library e VB-CABLE são dependências externas.
- O instalador não instala drivers de terceiros automaticamente.
- A configuração de CABLE Input/CABLE Output e o teste de escuta continuam sendo etapas explícitas.
- Câmera IP, áudio e instalador precisam de ensaio físico em uma máquina limpa antes de serem considerados certificados para uso em reunião.

## Não lançado — desenvolvimento após 21/09/2026

Consulte o histórico anterior desta versão no Git para detalhes de implementação, testes e telemetria.
