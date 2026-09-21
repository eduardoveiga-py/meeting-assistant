# Roteiro de conclusão — 21/09/2026

Requisitos ampliados pelo operador. O núcleo JWL ↔ Zoom continua congelado conforme o [contrato](validated-hall-contract.md). Novas funções usarão módulos separados e interfaces existentes.

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

A mudança de posição está pendente. Preservar callbacks/sinais e testar layout em resolução menor e escala ampliada. Rever também o rótulo do preview: a imagem atual é do OBS, não prova da saída física do Salão.

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

