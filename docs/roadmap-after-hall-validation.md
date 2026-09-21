# Roteiro de conclusão — 21/09/2026

Requisitos ampliados pelo operador. O núcleo JWL ↔ Zoom continua congelado conforme o [contrato](validated-hall-contract.md). Novas funções usarão módulos separados e interfaces existentes.

## Situação após os testes 1, 2 e 3 aprovados

Em 21/09/2026 o operador confirmou a nova referência 02094d8: fonte JWL, trocas de telas,
Windows+D, mídia e vídeo remoto. Baseline atualizado após essa confirmação, sem mover o checkpoint.
O lote seguinte implementa áudio, atalhos locais e organização de botões. O teste físico de áudio,
a câmera IP e o ensaio do instalador não estão aprovados por essa confirmação.

## Entregas e critérios de aceite

| Etapa | Entrega | Critério principal | Segunda tela? |
| --- | --- | --- | --- |
| 1 | Consolidar evidências de telas | Ciclos com automação ativa/pausada, mídia, Windows+D e reinício; retorno real ao JWL e isolamento do vídeo remoto | Sim, priorizar hoje |
| 2 | Foto do Texto do Ano em Ajustes | Capturar JWL, prévia, ano e gravação; atualizar fonte OBS; detectar falta e ano anterior | Captura real sim; regras não |
| 3 | Assistente OBS | Verificar/criar cenas e fontes; iniciar e confirmar câmera virtual; não duplicar nem sobrescrever ajustes pessoais | Estrutura/câmera não; captura física sim |
| 4 | Áudio JWL + microfones → OBS → Zoom | Fontes separadas e volumes corretos; não reenviar retorno Zoom | Não; exige mesa/interface real |
| 5 | Interface e fluxo da reunião | Ferramentas técnicas em Ajustes; consolidar início; encerramento assistido | Layout não; regressão física sim |
| 6 | Novas instalações | Primeiro uso, backup/restauração e vínculo local dos dispositivos | Parte física sim |
| 7 | Tutorial ilustrado | Instalar, configurar, operar, testar e solucionar problemas; imagens reais da interface final | Imagens de telas sim |
| 8 | Executável e instalador Windows | Funcionar sem Python/Git/bibliotecas instalados; detectar dependências externas e preservar dados | Windows limpo; monitor no teste físico |
| 9 | Ensaio completo e publicação | Reunião simulada, recuperação, guia, licenças e Release; tornar público quando o responsável decidir | Sim no ensaio final |

Entrega parcial em 21/09/2026: campos da câmera IP, criação/padronização de cenas e fonte Palco, parâmetros de abertura do OBS na bandeja/câmera virtual e opção de atalho no login. Sem teste físico da câmera; fontes de Texto do Ano/Mídias e confirmação da câmera virtual em OBS já aberto continuam pendentes. Demais etapas seguem planejadas.

## Foto do Texto do Ano

- Em **Ajustes → Texto do Ano**, oferecer **Criar foto** ou **Atualizar foto**, miniatura, ano de referência e data da captura.
- Capturar somente a região da janela secundária JWL, na resolução real, visível e sem mídia ou Zoom à frente. Bloquear sem saída válida, durante transição ou Zoom → Salão. Prévia e confirmação humana evitam salvar uma mídia como texto do ano.
- Salvar PNG e metadados na pasta de dados do usuário, com gravação atômica e preservação da imagem anterior em caso de erro. Verificar arquivo inexistente, ilegível e metadados ausentes.
- O ano de referência é confirmado pelo operador: data do arquivo não prova o ano do texto. Comparar na abertura e na virada do ano local; aviso adiável e opção para atualizar, sem interromper a reunião ou apagar a foto anterior.
- Atualizar apenas a fonte de imagem mapeada ao Fundo/Texto do Ano no OBS. Se desconectado, salvar localmente e indicar aplicação pendente; confirmar depois.
- **Foto do OBS e calibração do sensor são funções diferentes.** Salvar foto não recalibra nem ativa a automação.
- Testar primeira captura, substituição, cancelamento, ano anterior/virada de ano, arquivo apagado/corrompido, OBS offline e Zoom à frente.

## Assistente OBS

O diagnóstico atual confere nomes das cenas; falta verificar fontes, dispositivos, conteúdo e câmera virtual.

- Usar mapeamentos existentes de Fundo/Texto do Ano, Palco e Mídias. Zoom → Salão é saída local e não exige cena que reenvie o Zoom.
- Mostrar o plano antes de criar. Repetir sem duplicar cenas/fontes. Conflitos de nome/tipo exigem escolha; preservar cenas pessoais e oferecer backup da coleção.
- A estrutura é automatizável; câmera do palco, captura JWL e áudio precisam ser vinculados aos dispositivos reais. Fonte sem vínculo não significa configuração concluída.
- Em Iniciar reunião: aguardar OBS pronto, consultar câmera virtual, iniciar se parada e confirmar. Não usar toggle que possa desligar uma câmera já ativa; informar falha e permitir nova tentativa.
- Seleção da câmera no Zoom e áudio são verificações distintas. A câmera virtual não transporta o áudio.

## Auditoria dos botões

Todos os botões atuais têm ações conectadas; isso não comprova frequência de uso. Nenhum foi identificado como código morto.

| Controle | Próxima revisão |
| --- | --- |
| Fundo, Palco, Mídia | Manter: controle manual/contingência |
| Zoom → Salão | Manter |
| Ativar/Pausar automação | Manter |
| Cena segura → Palco | Manter: também pausa a automação, não duplica Palco |
| Iniciar reunião | Manter; acrescentar encerramento quando implementado |
| Verificar | Manter resumo rápido; detalhes técnicos em Ajustes |
| Ajustes | Manter |
| Observar mídia (20 s) | Mover para Ajustes → Diagnóstico |
| Calibrar Texto do Ano | Mover para Ajustes → Calibração; distinguir da foto |

A mudança de posição foi implementada neste lote (Ajustes → Ferramentas e áudio). Preservar callbacks/sinais e testar layout em resolução menor e escala ampliada. Rever também o rótulo do preview: a imagem atual é do OBS, não prova da saída física do Salão.

## Instalador e distribuição

Empacotar Python, PySide6 e bibliotecas junto com o app usando build Windows. Operador não instala Python nem executa pip. O instalador deve detectar OBS/Zoom/JWL e componentes de áudio, reutilizar existentes e baixar apenas ausentes de fontes oficiais, verificando integridade e tratando interrupções/reinícios.

Não prometer instalação silenciosa universal: administrador, Microsoft Store, drivers e termos de terceiros podem exigir interação. Onde não existir instalação automatizada suportada, apresentar a etapa oficial e retomar a verificação. Testar essa matriz em Windows limpo. Núcleo deve poder instalar offline; componentes externos ausentes exigem internet.

Atualizações preservam ajustes/foto; desinstalação oferece manter dados. Release futura inclui instalador e, se validada, versão portátil, guia ilustrado, licenças/avisos, notas e checksum. Revisar segredos e histórico antes da publicação. Não tornar público nesta etapa.

## Avançar em mais de um item

1. **Lote de telas:** foto + verificação das fontes OBS + evidências de regressão. Priorizar captura física enquanto há monitor.
2. **Lote sem monitor:** criação idempotente de cenas, câmera virtual, regras anuais/arquivos, interface e documentação. OBS real no notebook; telas ausentes/presentes simuladas em testes.
3. **Lote de áudio:** diagnóstico e roteamento enquanto amadurece o empacotamento; depende de conhecer mesa e retorno do Salão.
4. **Lote de entrega:** instalador em Windows limpo e tutorial ilustrado da interface estabilizada.

Testes simulados não certificam foco, geometria e exposição real no Windows. Sem o monitor, continuar itens independentes e reservar validação física antes de liberar.

## Evidência disponível e teste de hoje

Sessão MA-20260921-134522-4435: um ciclo confirmou Zoom em 266 ms e JWL em 344 ms, posição correta, não minimizados, sem cloak e expostos. Nenhum evento de severidade error nos 822 registros consultados. Isso confirma esse ciclo, não toda a matriz ou outras instalações.

Antes de devolver o monitor: três ciclos pausado e três ativo; reproduzir/parar mídia; Windows+D; reiniciar só o app; verificar remotamente que o Zoom não recebe o próprio retorno. Anotar resultado de cada cenário. Novas funções de captura/assistente OBS ainda exigem implementação/teste e não estão aprovadas por esse ciclo.

## Opcionais posteriores

Cronômetro, atalhos, controle remoto, lembretes e preparação de mídias. Veja a [pesquisa de reaproveitamento](reuse-assessment.md).


## Atualização do aplicativo pelo GitHub — nova pendência

Requisito adicionado pelo operador em 21/09/2026; **ainda não implementado**.

- Consultar Releases na inicialização em segundo plano, com timeout, sem bloquear a operação ou falhar quando não houver internet.
- Comparar versões de forma semântica; canal estável por padrão. Não instalar automaticamente pré-releases nem confundir a data de um commit com versão.
- Tela própria: versão instalada, versão disponível, notas da Release, tamanho, progresso de download, instalar agora/depois e erros recuperáveis.
- Nas Releases, separar **novidades**, **melhorias**, **correções**, **mudanças de configuração/migração**, **limitações conhecidas** e **testes realizados**. Informar requisitos Windows/OBS, versão e data.
- Baixar o artefato correspondente ao Windows/arquitetura em uso, verificar integridade/autenticidade conforme o mecanismo de distribuição escolhido e concluir a instalação fora da execução do app.
- Preservar configurações, foto do texto do ano e referências do detector; preparar recuperação da versão anterior. Não atualizar durante reunião/automação ativa.
- Instalador usa binário da Release; instalação de desenvolvimento precisa de fluxo distinto que preserve alterações locais, sem git pull automático nem sobrescrita silenciosa de código.
- Repositório privado exige acesso autorizado; nunca embutir tokens no executável. Depois da publicação autorizada, usar Releases públicas. Esta etapa não torna o projeto público.
- Testar: versão atual/nova, pré-release, offline, download interrompido/corrompido, disco cheio, permissões, atualização e recuperação. Entregar junto à fase de instalador/publicação.

Modelo de notas: [template de Release](release-template.md). Histórico em [CHANGELOG](../CHANGELOG.md).

## Entrega dos passos 1 e 2 — implementação, validação física pendente

- Em Ajustes há uma tela de captura, prévia, confirmação de ano, gravação e aplicação da foto no OBS.
- PNGs versionados e manifesto atômico; imagem anterior preservada em falha. Detecção de ausência/corrupção e aviso anual não modal, reavaliado na abertura e a cada minuto.
- Fonte de imagem gerenciada criada/atualizada na cena Fundo; arquivo salvo offline fica pendente e é aplicado na próxima conexão OBS local.
- Fonte Mídias usa janela JWL identificada, correspondência exata e única e áudio desativado; nunca usa captura de monitor/Zoom como fallback.
- Verificação de fontes, arquivos e estado da câmera virtual; Iniciar reunião solicita e confirma câmera virtual também com OBS já aberto.
- Métodos não alteram Program, guardiões, detector nem calibração. Conteúdo real da imagem e isolamento no Zoom ainda devem ser testados com o operador.
- Identidade ambígua no OBS impede aplicação. Esse resultado requer diagnóstico da lista de janelas; não enfraquecer a proteção para forçar sucesso.


## Repriorização e requisitos de 21/09 — segunda tela primeiro

1. **Agora, com monitor:** corrigir falsa sobreposição na captura, salvar/atualizar a foto,
   verificar ausência de faixa superior e preparar a fonte Mídias. Repetir Zoom → JWL,
   Windows+D e mídia → Palco; não atualizar o checkpoint sem confirmação do operador.
2. **Ainda com monitor:** validar seleção do monitor, imagem na assistência e isolamento do
   vídeo que volta para o Zoom. Capturar imagens reais para o tutorial.
3. **Depois, apenas notebook:** assistente de configuração, testes de instalação/atualização,
   atalhos e documentação; áudio exige dispositivos reais, mas não exige segunda tela.
4. **Release candidata:** ensaio do instalador Windows limpo e de atualização, configuração
   inteira pelo assistente, recuperação de falhas e teste final no Salão.

### Atalhos F1–F10 — escopo local implementado; teste físico pendente

Proposta inicial: F1 ajuda, F2 Texto do Ano, F3 Palco, F4 Mídias, F5 Zoom → Salão,
F6 ativar/pausar automação, F7 cena segura, F8 iniciar reunião, F9 verificar, F10 ajustes.
Mapeamento fixo com ajuda F1 e sem repetição por tecla mantida. Remapeamento permanece pendente.

- Primeiro escopo: somente com foco no app; suspender ações de operação enquanto houver
  edição de ajustes, diálogos ou instalação em andamento.
- Modo global opcional: registrar e liberar teclas com RegisterHotKey/UnregisterHotKey,
  detectar conflitos e oferecer remapeamento, sem desativar atalhos do Windows em geral.
- F1/F5/F10 têm comportamentos contextuais em outros programas; não são todos atalhos
  reservados do sistema. Não capturar combinações Alt/Ctrl/Win por consequência.
- Teclas Fn/volume/brilho podem ser tratadas pelo firmware e não equivalem a F1–F10.
- Testar com JWL, Zoom e OBS em foco, repetição, suspensão, fechamento e conflito.
  F12 fica fora do plano por ser reservada para depuração no Windows.

### Assistente na primeira instalação e após atualização — implementado, ensaio futuro

Disponível em Ajustes → Assistente de instalação e configuração. Uma única janela contém
formulário de ajustes, diagnóstico/preparação e foto/fontes. Executável empacotado oferece
revisão por versão; execução de desenvolvimento não abre o assistente automaticamente.

- Detecta OBS, Zoom, pacote JWL, link, conexão WebSocket, cenas, câmera virtual, monitor e foto.
- Salva ajustes sem fechar; instala OBS/Zoom via WinGet com consentimento na própria tela;
  WinGet verifica os pacotes. Não usa bypass de hash ou execução de URLs arbitrárias.
- JWL usa a instalação oficial; Microsoft Store/UAC/instaladores externos podem exigir
  janelas do Windows. O assistente permanece aberto e permite verificar novamente.
- Prepara WebSocket autenticado no OBS padrão fechado, com backup e escrita atômica;
  OBS portátil exige configuração pelo próprio OBS. Não fecha OBS à força.
- Cria cenas padrão sem apagar cenas existentes, configura câmera mediante ação explícita,
  reutiliza captura/foto/fontes e confirmação da câmera virtual.
- Revisão registrada não certifica áudio, vídeo, fonte IP nem comportamento físico; ensaios
  manuais permanecem identificados como pendentes. Arquivo de ajustes é preservado ao atualizar.
- Não realizado agora: instalação real, câmera IP, release, empacotamento e ensaio em Windows limpo.
- Antes da Release: garantir detecção de instalações não convencionais, tratamento de reinício,
  configuração de microfone/câmera/permissões Windows e Zoom e teste com/sem internet.

### Áudio — requisito esclarecido e arquitetura escolhida

A mesa já chega à entrada de microfone do notebook e o Zoom a usa diretamente. A falta atual
é o áudio dos aplicativos de mídia, pois a câmera virtual só entrega vídeo. Vamos manter a
ligação física e mudar a seleção de microfone do Zoom quando o novo caminho for validado.

- OBS mistura **entrada da mesa + captura por aplicativo** (JWL, VLC, Chrome/Edge escolhidos).
- Mix enviado por monitoramento ao **CABLE Input**, do VB-CABLE. No Zoom, microfone será
  **CABLE Output**. Alto-falante do Zoom continua na saída física que atende o Salão.
- Não capturar Zoom nem o Desktop Audio inteiro. Não reenviar o retorno remoto para o cabo.
- Criar barramento de áudio persistente nas três cenas para evitar corte quando o detector
  mudar de cena; volume/mute independentes da escolha de vídeo. Não capturar novamente o
  áudio da fonte de vídeo JWL se já houver captura dedicada do aplicativo.
- Conferir mesa: a saída ligada ao notebook deve excluir o retorno Zoom (mix-minus). Se
  já incluir a mídia do computador, impedir a segunda cópia no OBS ou separar o envio da mesa.
- Não monitorar a mesa de volta às caixas pelo OBS; a mesa já faz a sonorização local.
  As mídias continuam tocando localmente pela saída atual, além da cópia destinada ao Zoom.
- Validar voz sozinha, mídia sozinha, voz+mídia, comentário remoto sem retorno, troca de
  cena, navegador com título variável, reinício e reconexão. Teste remoto deve usar fones.
- Captura por aplicativo tem limitações de compatibilidade; quando falhar, estudar saída
  dedicada de mídia por segundo cabo/roteador virtual. Não recorrer ao áudio total do PC.
- Módulo de preparação/ativação implementado. Nenhuma configuração de áudio é aplicada
  automaticamente na abertura. Escuta real com mesa e Zoom permanece pendente.
- [Roteiro e formulário de retorno](test-audio-shortcuts.md).

Referências: [captura por aplicativo OBS](https://obsproject.com/kb/application-audio-capture-guide),
[VB-CABLE](https://vb-audio.com/Cable/),
[RegisterHotKey](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey),
[WinGet install](https://learn.microsoft.com/en-us/windows/package-manager/winget/install).
