# Histórico de alterações

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
