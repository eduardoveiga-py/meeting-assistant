# Registro de decisão

O [histórico de incidentes](incident-history.md) reúne sintomas, soluções,
confirmações e aprendizados desta conversa. Este arquivo registra as decisões
técnicas; os roteiros específicos mantêm os detalhes de teste.

## 2026-10-07 — Ajustes unificados, manutenção incremental e volumes

**Retorno posterior:** o operador aprovou a organização dos Ajustes na revisão
`7a7697a`: “Os ajustes ficaram ótimo!”. Aceite limitado à interface relatada;
instalação de plugins, escuta de áudio e manutenção repetida têm ensaios próprios.
Volumes/Ajustes recebem ícones SVG na mesma célula, com os rótulos preservados.

**Solicitação:** a quantidade de subjanelas tornou configuração e manutenção
confusas. O operador pede opções por assunto, fontes/plugins mais fáceis de
preparar e volume acessível, preservando layout e dados.

**Decisão:** uma janela com navegação por categorias, reutilizando os editores
existentes. Separar controles cotidianos de níveis das escolhas de roteamento;
acesso Volumes ocupa parte da célula Ajustes existente. Navegação e consultas
não reconectam OBS nem recriam fontes. Salvar campos gerais parte dos ajustes
atuais para preservar ganhos confirmados enquanto a janela está aberta.

O serviço de manutenção verifica cenas, foto, câmera IP, captura HWND, estrutura
de áudio e plugins. A conclusão atua somente nos itens ausentes, preservando
nomes mapeados e ajustes existentes. Nomes/tipos conflitantes, fontes duplicadas
ou desativadas exigem revisão. **Completar fontes de áudio** substitui a preparação
silenciada descrita no registro de 03/10: mantém o envio existente; somente
fontes novas começam silenciadas e desativadas. Mudar dispositivos/ativar envio
continua uma ação explícita.

Plugins ficam na categoria de instalação, em worker, com OBS fechado e
autorização da operação. Audio Monitor 0.10.1 usa ZIP oficial, SHA-256 fixado,
arquivos x64/traduções limitados, backup e conferência posterior. Componentes
JWL/câmera reutilizam scripts que obtêm binários prontos; não há compilação,
mudança de backend nem alteração do núcleo protegido.

**Evidência:** testes da interface percorrem a fila do controlador com OBS
simulado; cobrem navegação sem escrita, ganho independente, mescla de salvamento,
cancelamento de fechamento e preparação repetida. Manutenção cobre fontes
apagadas parcialmente, conflitos, falhas e preservação de RTSP/filtros.
Instalação testa integridade, caminhos do ZIP, OBS fechado e repetição sem cópia.
Layout é renderizado em quatro escalas. Instalação real, dois monitores e escuta
das chamadas desta revisão continuam dependentes do operador.

[Mapa de Ajustes e roteiro de aceite](settings-workspace.md).

## 2026-10-07 — apresentação de mídia externa restaurada antes da captura

**Problema demonstrado:** inventário nativo oferecia players minimizados,
enquanto a lista de captura OBS os exclui. Preparar a captura antes de restaurar
impedia a apresentação. Cancelamento durante preparo perdia a cena anterior;
falhas posteriores perdiam o motivo original. O relato do operador não inclui
a mensagem exata e não há diagnóstico sincronizado atual para atribuição única.

**Decisão:** preflight OBS sem escrita, snapshot de Program e da janela
identificada, apresentação nativa em worker, leitura atualizada do título e
captura exclusiva Player. Cancelamento espera a resposta antes de rollback.
Identificar cada ciclo; invalidar pedidos de cena anteriores à suspensão, mantendo
as mudanças manuais do OBS. A identificação externa respeita capitalização OBS
sem aceitar títulos ambíguos ou captura de monitor. Fontes JWL/áudio não mudam.

**Evidência:** regressões de cliques reais Qt, fila OBS e workers com backends
simulados reproduzem as falhas; incluem dois ciclos, retorno confirmado,
falha parcial e preservação da disposição/áudio. Aceite físico da correção
permanece pendente. [Procedimento](external-media.md), INC-033.

## 2026-10-03 — leitura sem interrupção e volumes independentes

**Retorno:** a nova captura mostra perfil com retorno Zoom e segundo cabo não
selecionado. O operador considera a configuração confusa e continua sem ativar.
Além do campo ausente, foi encontrado erro na enumeração: `device.state == 1`
descartava o `AudioDeviceState.Active`, um Enum usado pelo pycaw 20240210 fixado
no projeto. Fontes primárias conferidas: [utils.py](https://github.com/AndreMiras/pycaw/blob/v20240210/pycaw/utils.py)
e [constants.py](https://github.com/AndreMiras/pycaw/blob/v20240210/pycaw/constants.py).

**Decisão:** comparar o valor do estado, preservando compatibilidade com wrappers
inteiros. Separar UI em Envio, Volumes e Ajuda; uma confirmação explícita cobre os
dispositivos das chamadas e o caminho físico. Ativar explica e foca uma pendência
em vez de permanecer desabilitado. Não dispensar segundo cabo nem mix-minus.

Abertura/atualização agora usa ação `inspect` somente de leitura na fila serial
existente. Criação de fontes continua explícita e silenciada. A ação `gains`, em
módulo separado, valida filtros de fontes gerenciadas e altera somente os ganhos
editados; confirma leitura e tenta restaurar valores em falha. Não cria fontes,
reativa filtros, troca destinos ou silencia o áudio. A UI lê os ganhos já presentes
no OBS e salva somente resultados confirmados.

**Evidência:** testes usam o mesmo formato Enum da biblioteca, incluindo exclusão
de dispositivos inativos/captura/físicos, liberação COM e validação do segundo
cabo. Cliques Qt percorrem serviço OBS simulado nos dois perfis, incluindo ganho
sem segunda seleção/confirmação, atualização sem interrupção, falha de escrita,
remoção de dispositivo e layouts/fontes ampliados. Ensaio físico pendente.

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

As medidas nativas identificaram o botão de preparação: seu título longo impunha
394 px a uma área de 332 px. O título agora é **Preparar fontes**; atualizar as listas
continua na mesma ação e está descrito no tooltip. O teste salva a imagem antes de
verificar medidas, confere todo o texto do botão e a altura variável dos rótulos.
As políticas desses rótulos preservam a dependência entre altura e largura.

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

## 2026-10-07 — captura direta da saída JWL

**Decisão:** fonte OBS independente por HWND, usando o backend GPU `libobs-winrt`
do próprio OBS. A captura padrão por título/classe/executável não distingue as
duas janelas JWL com títulos iguais. Não usar captura de monitor como fallback,
nem trocar o player, áudio, ponte Program ou câmera virtual.

**Evidência:** código upstream do OBS confirma seleção por título/classe/executável.
A implementação nova passa o HWND identificado pelo núcleo existente e verifica
PID/geração, relação UWP, classe e papel do monitor. CI Windows compila a DLL,
testa a política de identidade e verifica integridade. Python confirma diagnóstico
nativo, migração sem apagar fontes e bloqueio de feedback inclusive em simulação.

**Entrega:** `git pull` e `scripts/run.ps1` baixam o componente pronto com SHA-256
fixado. Nenhuma compilação local ou novo instalador do app é exigido neste lote.
[Arquitetura, limites e estado de validação](jwl-capture-candidate.md).

## 2026-10-07 — aceite da captura e atualização preservando trabalho local

**Retorno físico:** após atualizar o projeto e executar pelo Python, o operador
confirmou: “Excelente! Funcionou perfeitamente!”. Revisão entregue: `e9bf684`;
componente `jwl-capture-v1.1`. O ambiente declarado é Windows 11 com dois monitores;
não foram enviados versões exatas OBS/JWL, diagnóstico ou resultados individuais
de reinícios e de todos os cenários do contrato.

**Decisão:** registrar a captura JWL por HWND como confirmada no uso relatado.
Manter a matriz de regressão operacional e os hashes históricos separados desse
aceite. Não reclassificar como concluídas a otimização Mic Zoom, o ruído OBS ou
a visualização de vários participantes por causa dessa confirmação.

**Obstáculo da atualização:** `git pull --ff-only` recusou sobrescrever
alterações locais em decisão e segurança de captura. Elas foram guardadas com
`git stash push --include-untracked`; a orientação passou a verificar
`$LASTEXITCODE` antes de atualizar/executar. O stash não foi coletado nem
reaplicado automaticamente.

**Aprendizado:** identidade por título/classe/executável não distinguia as
janelas JWL; a nova fonte resolve a ambiguidade pelo HWND sem liberar captura de
monitor. Preservar trabalho local e confirmar o resultado do Git evita testar
código antigo. [Casos INC-030/031 e histórico completo](incident-history.md).
