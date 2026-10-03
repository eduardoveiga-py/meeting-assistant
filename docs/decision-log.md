# Registro de decisão

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
