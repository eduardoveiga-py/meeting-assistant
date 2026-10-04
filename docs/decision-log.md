# Registro de decisão

## 2026-10-03 — pendências visíveis na ativação do áudio

**Problema relatado:** fontes criadas no OBS, três confirmações marcadas e botão
Aplicar desabilitado. A captura não mostra os campos de entrada/destino; não permite
atribuir a falha real a um deles. O código exige mesa e, no perfil com Zoom, segundo
cabo, mas não explicava essa pendência. Atualizar as listas também descartava
seleções editadas quando os ajustes salvos no OBS não correspondiam a elas.

**Decisão:** exibir os campos pendentes no rodapé e mostrar o primeiro após preparar.
Preservar escolhas disponíveis e ganhos na mesma tela; não selecionar substitutos
de dispositivos removidos nem dispensar confirmação do roteamento. Ganho de fonte
não selecionada fica desabilitado. Rede e filtros continuam no serviço OBS existente.

**Evidência:** testes de cliques/teclas Qt reproduzem o bloqueio com confirmações
marcadas, atualização após recriar entradas, remoção de dispositivos e troca de
perfil. O clique Aplicar percorre o serviço de áudio com OBS simulado, confirma ganho
e verifica que o retorno Zoom vai somente ao segundo cabo. Ensaio físico pendente;
esta alteração não diagnostica nem remove o ruído relatado na entrada da mesa.

**Layout no Windows:** a primeira execução do CI encontrou rolagem horizontal na
menor área do teste (390 × 410). Rótulos acima dos campos e parágrafos usam um layout
vertical e podem encolher na horizontal, preservando todo o texto por quebra de linha,
os campos e os botões. O teste define a fonte dos controles por
estilo local, pois o estilo herdado pode ignorar a fonte escolhida apenas no diálogo.
Isso amplia o texto sem alterar outras janelas da suíte; todos os rótulos são
verificados além do rodapé. A seleção por teclado usa uma quantidade limitada de
eventos e exige alcançar o item esperado, sem laço infinito se uma tecla não atuar.

**Isolamento do CI:** o diagnóstico de uma execução parada encontrou um teste
antigo de recuperação chamando `os.startfile("whatsapp://")` no Windows real.
O helper desse teste agora simula a abertura e verifica a URI solicitada, evitando
aplicativos/diálogos externos. O serviço de inicialização do app não foi alterado.

## 2026-09-17 — saída do Salão

**Decisão:** manter o JW Library como player e usar sua segunda janela nativa como saída física do Salão.

**Motivo:** reduz camadas, preserva o fluxo do operador e permite reaproveitar técnicas maduras de identificação/proteção de janela já usadas por ferramentas da comunidade.

**Consequência:** `HallOutputWindow` própria deixa de ser o caminho principal. O detector visual usa somente a segunda janela identificada do JW Library e uma referência persistente do estado de repouso.

## 2026-10-03 — microfone próprio do Zoom

**Decisão:** o clique consulta e alterna o estado real no worker; o cache da UI serve
apenas à apresentação. A identificação usa evidência de acessibilidade do controle
próprio, incluindo UIA/legacy, sem depender de uma única classe de janela ou de
comandos globais de teclado. Consultas periódicas não descartam cliques.

**Evidência:** regressões reproduziram o clique sem ação com estado desconhecido ou
antigo e a interpretação incorreta de comandos de vídeo/legendas. A correção inclui
cliques da UI, fila limitada, confirmação, falhas e diagnóstico sem dados pessoais.
Zoom real permanece pendente de ensaio. [Roteiro](zoom-microphone-control.md).

**Ajuste após retorno físico:** a imagem do novo teste identificou o bloqueio
`identity_unavailable`. RuntimeId deixa de ser requisito para o clique: identidade
lógica vincula o microfone próprio a uma única janela/instância do Zoom, com estado
acessível consistente. RuntimeId disponível serve somente à deduplicação; candidatos
sem ele não são fundidos. Regressões reproduziram o bloqueio e cobrem o fluxo Qt/COM/
UIA, reconstrução do botão, ambiguidade e troca de janela/processo. Novo teste do
Zoom real permanece pendente; não há telemetria sincronizada desse ensaio.

**Retorno e otimização:** o operador confirmou que abrir/silenciar funcionou após
a correção de identidade, com aproximadamente cinco segundos de demora. Manter
um único worker COM MTA e a referência do microfone; reler propriedades atuais,
processo/janela/papel a cada ação, com nova descoberta quando invalidado. A busca
fria é filtrada pelo processo Zoom. Confirmar imediatamente, esperando apenas
entre leituras sem confirmação, e registrar os tempos por fase. Não transferir
elementos COM entre workers nem usar o cache de mute da GUI para decidir a ação.
Os testes medem a redução de varreduras no backend simulado; a latência real desta
nova revisão permanece pendente. O núcleo de telas/áudio/vídeo não foi alterado.
