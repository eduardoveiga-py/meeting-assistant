# Histórico de alterações

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

