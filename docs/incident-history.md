# Histórico de problemas, soluções e aprendizados

Consolidado em **07/10/2026** a partir dos relatos do operador nesta conversa,
dos registros existentes e do código entregue até
`e9bf684aaa0b522c351691c2b1e5729909856012`.
Este arquivo complementa o [registro de decisões](decision-log.md);
os documentos técnicos vinculados continuam descrevendo cada implementação.

A organização de Ajustes de 07/10/2026 recebeu aceite limitado à interface
na revisão `7a7697a` (INC-032). Mídia externa foi relatada com conflito
na mesma sessão (INC-033). Após a entrega `8937c75`, o operador confirmou guardião
e Forçar JWL; seletor/posicionamento externo funcionam, mas apresentação e
retorno continuam com defeito. Correção externa de 08/10 exige ensaio próprio.
Hash exato do checkout local não enviado. Nenhum retorno estende o aceite
a comportamentos não testados.

## Como interpretar o registro

- **Confirmado pelo operador**: houve retorno explícito no equipamento real,
  limitado ao comportamento relatado e à revisão testada.
- **Implementado; ensaio pendente**: código/testes existem, mas não há aceite
  físico específico da correção mais recente.
- **Contorno relatado**: uma forma de operar funcionou, sem causa raiz demonstrada.
- **Pendente**: o histórico disponível não permite declarar resolução.
- **Encerrado por decisão**: a alternativa foi abandonada por mudança autorizada
  de requisito; isso não significa que ela foi tecnicamente consertada.

Quando o chat informa apenas o sintoma ou a confirmação, não atribuímos a ele
uma causa, medição ou commit ausente. Screenshots antigos citados no chat não
foram reinspecionados nesta consolidação. Relatos de telemetria já registrados
nos documentos são evidência histórica; nenhuma telemetria da máquina do
operador foi coletada novamente nesta tarefa.

## Índice

| ID | Problema | Situação |
| --- | --- | --- |
| INC-034 | Forçar JWL gera AttributeError repetido | Operador confirmou funcionamento após entrega `8937c75` |
| INC-035 | Qt amplia Ajustes além do tamanho solicitado | Restrição nativa reproduzida/corrigida; ensaio na escala do operador pendente |
| INC-033 | Mídia externa falha após escolher a janela | Reaberto após 7a5f7db: cessão persistente/popup candidatos, ensaio pendente |
| INC-032 | Ajustes fragmentados e manutenção de fontes frágil | Organização aprovada em 07/10; manutenção/instalação com ensaio próprio |
| INC-030 | OBS escolhia o JWL do operador entre títulos iguais | Captura por HWND confirmada em 07/10 |
| INC-031 | Git bloqueava atualização por alterações locais | Atualização e execução confirmadas em 07/10 |
| INC-001 | JWL carregava e fechava na primeira abertura | Contorno relatado; causa externa não confirmada |
| INC-002 | Windows+D não restaurava imediatamente a saída JWL | Correção confirmada historicamente |
| INC-003 | Repouso/Texto do Ano interpretado como mídia | Automação confirmada historicamente |
| INC-004 | Janela alta e botões fora da área útil | Ajustes confirmados historicamente |
| INC-005 | Layout estourava na horizontal | Correção confirmada; revisar após novos textos |
| INC-006 | Cabeçalho desaparecia apesar dos testes | Correção com regressão/renderização; aceite específico pendente |
| INC-007 | Segunda janela Zoom não encontrada | Fluxo corrigido historicamente |
| INC-008 | Retorno Zoom → JWL lento ou janela Zoom fechada | Troca confirmada no contrato histórico |
| INC-009 | Vários participantes não apareciam juntos no Zoom secundário | Pendente |
| INC-010 | Borda superior criada na saída JWL | Correção confirmada historicamente; causa exata não registrada |
| INC-011 | Foto recusada por sobreposição/ordem falsa | Captura e salvamento confirmados historicamente |
| INC-012 | Foto salva, mas aplicação OBS rejeitada como remota | Reconhecimento do host local corrigido; ensaio específico pendente |
| INC-013 | Conexão OBS só funcionava após reabrir o app | Recuperação relatada; causa do episódio não confirmada |
| INC-014 | Câmera DirectShow Windows 10 ausente no WhatsApp | Encerrado por decisão: Windows 11 |
| INC-015 | Bridge/prévia com poucos quadros | Fluxo nativo melhorado; taxas observadas no histórico |
| INC-016 | Câmera Windows 11 funcionava, mas recepção travava | Etapa aceita; CPU quase saturada relatada |
| INC-017 | PowerShell bloqueava scripts | Execução por processo funcionou |
| INC-018 | Dependências pycaw/Python incompatíveis | Correção de versões confirmada |
| INC-019 | Checksum da DLL divergente | Integridade mantida; distribuição corrigida no fluxo atual |
| INC-020 | DLL de câmera em uso durante instalação | Procedimento de atualização com consumidores fechados |
| INC-021 | Mídias sem áudio em Zoom/WhatsApp | VB-CABLE/OBS confirmados no Salão |
| INC-022 | Ícone de mute confundido com monitoramento | Semântica esclarecida; conferir rota e escuta |
| INC-023 | Cena de áudio e fontes repetidas em várias cenas | Estrutura compartilhada prevista; evitar duplicação de rotas |
| INC-024 | Volume remoto baixo com fader OBS no máximo | Ganho/limitador implementados; níveis exigem teste de escuta |
| INC-025 | Aplicar áudio bloqueado e configuração confusa | UI/enumeração corrigidas; novo perfil exige ensaio |
| INC-026 | Ruído da mesa somente dentro do OBS | Pendente |
| INC-027 | Botão Mic Zoom sem ação | Funcionamento confirmado após correção de identidade |
| INC-028 | Mic Zoom levava cerca de cinco segundos | Otimização implementada; latência real pendente |
| INC-029 | Windows bloqueava executável sem fornecedor verificado | Distribuição/assinatura pendentes |

## INC-034 — Forçar JWL falha no slot da interface

**Relato e revisão.** Em 07/10/2026, antes de executar a atualização anterior,
o operador enviou tracebacks repetidos de `_force_jwl`: `AppSettings` não possui
`automation_enabled`. A revisão local não foi informada. O mesmo defeito está
presente em `af55369`, a revisão diagnosticada nesta correção.

**Causa demonstrada.** O slot mistura configurações persistidas com AppState e
referencia `automation_toggle`, `zoom_hall_button` e `hall_guard`, que não existem
no MainWindow atual. Somente substituir settings por state produziria novos
AttributeErrors e habilitaria automação indevidamente. Nove testes de clique
reproduziram a primeira exceção, capturando o sys.excepthook usado pelo Qt.

**Correção.** Usar o retorno explícito existente, com confirmação posterior.
Preservar automação e configurações; não mudar Program nem o estado visual Zoom
antes de confirmar. Se houver mídia externa, solicitar o retorno pelo serviço
externo para restaurar Program/player antes do JWL. Preservar a mensagem específica
de falha e informar recusa quando o serviço não inicia o retorno.

**Aprendizado e limite.** Clique conectado e suíte verde não comprovam que todos
os slots foram exercitados. Exceção num slot PySide pode ser impressa sem falhar
o teste: verificar o caminho real e capturar essa exceção explicitamente.
Serviços JWL/Zoom protegidos não mudaram.

**Retorno seguinte.** Após entregar `8937c75`, o operador confirmou guardião e
o botão que traz JWL à segunda tela. Hash local não enviado; aceite limitado
às ações relatadas. O defeito externo posterior está separado no INC-033.

## INC-035 — Aviso QWindowsWindow::setGeometry nos Ajustes

**Relato.** O mesmo terminal registra tamanho pedido 930×939 e resultado 930×1002.
É um aviso de geometria Qt, separado do AttributeError; o log não identifica
qual categoria estava aberta. Não representa uma borda na saída JWL.

**Falha demonstrada.** fit_window deixa o formulário dentro da área útil no
backend de teste, mas QLayout.closestAcceptableSize pede altura maior, sobretudo
após selecionar Áudio. O viewport nativo Windows consulta essa restrição.
QStackedLayout considera também páginas ocultas no cálculo da altura pela largura;
uma mudança de categoria pode exigir mais altura que a disponível.

Referências primárias Qt: [restrição da janela](https://github.com/qt/qtbase/blob/v6.10.2/src/widgets/kernel/qwidgetwindow.cpp),
[tamanho aceito pelo layout](https://github.com/qt/qtbase/blob/v6.10.2/src/widgets/kernel/qlayout.cpp)
e [pilha de páginas](https://github.com/qt/qtbase/blob/v6.10.2/src/widgets/kernel/qstackedlayout.cpp).

**Correção.** Um viewport Qt limita a pilha de páginas, sem propagar essa altura
ao diálogo nativo. Navegação/rodapé e ações de áudio ficam nas áreas existentes;
cada página conserva sua rolagem, sem outra barra externa. Não suprimir o aviso.

**Aprendizado e limite.** Geometria aparente em Linux pode caber e ainda ser
recusada pelo Qt nativo. Acrescentados testes de closestAcceptableSize, abertura
e troca de categorias, quatro escalas e recusa de setGeometry em stderr.
A ausência do aviso no equipamento/escala do operador exige novo ensaio.

## INC-033 — Mídia externa falha depois da seleção

**Reabertura após `e072427`.** O operador relatou a mesma mensagem, agora sem
mover a janela para a segunda tela. CI anterior passou, mas não constitui aceite
físico. Diagnósticos remotos continuam somente até 02/10; causa local não confirmada.

**Falha adicional reproduzida.** O estilo salvo incluía os bits de estado
WS_MINIMIZE/WS_MAXIMIZE. Depois de pedir SW_RESTORE assíncrono, aplicar o estilo
salvo podia reaplicar minimização/maximização. A simulação antiga representava
minimized=True sem o flag de estilo correspondente; não detectou a sequência.

**Nova candidata.** Esperar restauração normal/visível antes de ocultar JWL e
alterar somente a borda do player com os estilos atuais. Preservar snapshot
original para retorno. Erros distintos informam restauração, posição, cloaking,
cessão ou exposição; falha nativa informa etapa/tipo/código sem conteúdo privado.
Prova Windows separada cria HWNDs próprios e bombeia mensagens na thread dona,
testando APIs reais em normal/minimizado/maximizado. Não controla apps do operador.
Simulação reproduz flag reaplicado, atraso, estilos atualizados e timeout que
preserva JWL. O roteiro físico permanece pendente; pedir ZIP do diagnóstico se
falhar, em vez de inferir outra causa pela mensagem genérica.

**Aprendizado adicional.** Propriedade booleana simulada não substitui flags e
fila reais. Snapshot pertence à restauração final, não à escrita integral no
início. Validar chamadas reais do Windows além de integrar UI/serviço em mocks.

**Resultado do primeiro CI nativo (`3a0273f`):** normal/min/max travaram; 649
regressões restantes passaram. Não promovido para main. O wrapper upstream
SetWindowLong retém o GIL durante a chamada que pode notificar a thread GUI;
esta prova usa callback Python, tornando o bloqueio observável. Escrita de
estilo externa passa a usar WinDLL tipado, que libera GIL e verifica código
Windows. O subprocesso de prova preserva esse cenário e fornece tracebacks
em timeout. Apenas o novo ensaio deve confirmar a correção do bloqueio.

**Reabertura após `7a5f7db`.** O operador viu o player à frente por um momento,
mas não permaneceu. A imagem confirma a mensagem “Player não ficou visível à
frente do JWL no Salão” seguida do retorno confirmado ao JWL. A candidata
anterior não foi aceita. Sem telemetria atual desse ensaio: não atribuir a
causa real exclusivamente ao guardião ou ao Windows.

**Candidata seguinte.** Cessão explícita: só a saída secundária JWL identificada
é ocultada temporariamente, mantendo processo/HWND e geometria. Resolve frame
UIA/filho CoreWindow e valida PID host/filho; ausência ou identidade divergente
aborta sem escolher pelo título. Observação durante toda apresentação refaz
cessão/exposição sem ativação repetida. Retorno e encerramento liberam JWL.

Popup modeless no primeiro monitor fornece controles de reprodução e retorno.
Chrome/Edge usam controles acessíveis da aba visível; VLC usa seus próprios
botões, sem teclas globais. Parar serializa comando pendente, interrupção da
mídia, retorno de Program, player ao monitor principal e confirmação JWL.
UIA com processo isolado/prazo evita deixar um comando pendente na GUI;
pausa não confirmada fica como aviso, sem bloquear a recuperação do Salão.

**Evidência/limite.** Regressões reproduzem reaparecimento tardio, PID UWP,
HWND filho, inventário UIA temporariamente vazio e retorno pelo frame retido, clique/cancelamento do popup, estado já desejado, ambiguidade e
provider travado. Renderização em quatro escalas; núcleo protegido mantido.
Isso não comprova vídeo/controles reais no Chrome/VLC. Novo ensaio de 30 s e
ciclos pausados/ativos pendente em [external-media.md](external-media.md).

**Aprendizado novo.** Cessão e exposição precisam durar o ciclo inteiro. Uma
identidade UIA e sua representação Win32 podem diferir legitimamente; não
ignorar a operação em silêncio. Ler estado do player evita alternâncias por
Espaço; atalhos de site não são comandos genéricos de navegador.


**Reabertura após entrega `8937c75`.** Seleção/posicionamento funcionam, mas
JWL fica à frente e Parar mídia não retorna. Sem telemetria sincronizada desse
ensaio. O modelo Win32 reproduz sucesso falso: player posicionado, coberto
pela janela JWL em tela cheia. O botão decide pelo checked Qt, falhando quando
diverge do serviço. O retorno também fazia leitura imediata após pedido nativo,
sem confirmar minimização/exposição. São falhas demonstradas no código/testes;
a causa única do episódio real não foi atribuída sem diagnóstico.

**Correção candidata de 08/10.** Backend externo cede prioridade somente da
saída JWL identificada, sem mexer em sua borda/tamanho. Confirma exposição,
geometria e cloaking, com uma tentativa de ativação; confere novamente após
preparar OBS. Parar/Cancelar usa o estado do ciclo; retorno restaura Program e
disposição do player por pedido assíncrono com confirmação limitada. O retorno
JWL existente confirma visibilidade antes de retomar guardião/sensor. Falha
mantém motivo e botão Repetir retorno. Diagnóstico inclui resultados nativos,
sem títulos/URLs. Worker que concluiu mas ainda emite o resultado não bloqueia
outro ciclo; inventário cancelado ainda em execução continua bloqueando.

**Evidência nova.** Backend Win32 real contra modelo de tela cheia, fila OBS,
painel/seletor reais, workers e dois ciclos com automação pausada/ativa. Cobrem
ativação recusada, retorno atrasado, HWND reutilizado, checked divergente,
cancelamento na confirmação e repetição de retorno falho. São simulações de
Windows/OBS; saída física e escuta exigem operador. Manifesto, núcleo protegido,
DLLs e fontes de áudio permanecem preservados.

**Aprendizado adicional.** Posicionar não comprova exibição. O comando pertence
ao ciclo do serviço. Pedidos assíncronos precisam de leitura posterior; testar
o clique Parar, além de selecionar ou chamar stop diretamente.

**Relato.** Em 07/10/2026, o operador informou que a lista abre, mas a escolha
da mídia externa gera conflitos. Não enviou a mensagem exata neste retorno.
O repositório de diagnósticos consultado estava atualizado somente até 02/10;
não há telemetria sincronizada desse ensaio para atribuir-lhe uma causa única.

**Falhas demonstradas.** O inventário do app oferece players minimizados; a
lista de captura de janela do OBS os exclui. O fluxo antigo tentava selecionar
no OBS antes de restaurar o player. Um teste integrado reproduziu o retorno a
idle sem apresentar essa janela. Outros dois testes reproduziram cancelamento
usando cena anterior ainda não confirmada e falha de preparação sem retorno
da janela/mensagem original. A seleção também reutilizava mensagem específica
do JWL e comparava o seletor com capitalização rígida.

**Correção candidata.** Conferir OBS/nomes sem escrita; salvar Program atual;
revalidar a identidade do player e guardar sua disposição atual uma vez;
restaurar/posicionar; reler o título e configurar a fonte Player exclusiva;
revalidar e só então pedir a cena externa. Cancelamento aguarda o resultado
pendente antes de desfazer. Falha restaura a disposição do player e solicita
retorno explícito ao JWL, mantendo seu motivo na mensagem final.

Respostas recebem identificação do ciclo para impedir uso de resultados antigos.
Pedidos de cena do app recebem geração; os que antecedem a suspensão ou chegam
durante a apresentação não podem ser executados depois do retorno. Alterações
manuais feitas diretamente no OBS continuam preservadas. Guardião/sensor só
retomam após o JWL confirmar visibilidade. O seletor usa índice, não procura
o primeiro texto igual entre duas opções.

**Proteções mantidas.** Títulos iguais continuam recusados pelo backend de
captura: o OBS pode escolher pelo título sem distinguir processos/classes.
Não há captura de monitor como alternativa; nenhum arquivo protegido ou DLL
JWL foi modificado. A fonte Player não captura áudio; mix/filtros/ganhos existentes
e captura JWL permanecem independentes.

**Evidência/limite.** `tests/test_external_media_flow.py` percorre cliques do
painel/seletor, workers reais com OBS/Win32 simulados, dois ciclos, minimização,
título atualizado/capitalização, cancelamento por fase, falha parcial, mensagens,
identidade do ciclo, pedidos antigos e preservação de áudio/Program manual.
Testes de layout do painel incluem os novos ícones em quatro escalas. Isso não
comprova o conteúdo do player nem áudio/chamadas físicas; repetir o
[roteiro de mídia externa](external-media.md) no Windows 11.

**Aprendizado.** Inventário Windows e lista de propriedades OBS têm critérios
diferentes de visibilidade. Confirmar a conexão não confirma captura. Uma ação
cancelada precisa consumir seu resultado antes de desfazer; estado antigo não
é um rollback confiável. Distinguir erro de mídia externa de erro da captura JWL.

**Reabertura com telemetria (08/10/2026).** O operador relatou a mesma falha: o
app esconde a tela principal e a janela do Chrome não vai para a segunda tela.
A mensagem registrada na telemetria foi: `"message":"Posicionamento não confirmado [WINDOW_API:player_restore]: NameError"`.

**Causa demonstrada.** A tentativa anterior de remover o estado maximizado do
Chrome introduziu um `NameError` (chamada `win32gui.SetWindowPos(...)` num escopo
onde apenas o alias `gui` estava definido e o módulo `win32gui` não estava
importado globalmente). Esse erro impedia a continuação do código, interrompendo
a exibição e disparando a reversão de segurança.

**Correção.** Removida a tentativa de forçar a remoção do estado maximizado do
player via API antes do reposicionamento. O player maximizado já cumpre as
condições necessárias (visível e não minimizado). A remoção das bordas e o
redimensionamento subsequentes sobrescrevem o estado maximizado nativo com as
coordenadas exatas fornecidas por `SetWindowPos` na etapa seguinte. Os testes da
camada Win32 foram validados.

**Reabertura com erro de posicionamento (08/10/2026).** Na segunda tentativa de
08/10, a telemetria indicou: `[PLAYER_POSITION] O player não confirmou o tamanho/posição no monitor do Salão`. O Chrome foi para a segunda tela e logo retornou.
A geometria registrada mostrava: `target_rect=[1920,0,3712,828]`,
`rect=[1913,-7,3719,787]`.

**Causa demonstrada.** A correção anterior permitiu a continuação do Chrome maximizado, mas
não retirou a flag nativa `WS_MAXIMIZE`. Quando a função `SetWindowPos` foi
chamada com a geometria exata do monitor (1920x828), o gerenciador de janelas do
Windows aplicou a regra de maximização, estendendo as bordas invisíveis (DWM
extended frame bounds) em -7 pixels, resultando em uma diferença de tamanho que falhou na validação de geometria estrita (`abs(a - b) <= 12`).

**Correção.** A flag `WS_MAXIMIZE` agora é removida junto com `WS_CAPTION` e
`WS_THICKFRAME` no momento exato em que a janela está sendo posicionada no
Salão (`present()`). Isso permite que o Windows aplique as coordenadas exatas
solicitadas. No retorno (`restore_presentation()`), a flag `WS_MAXIMIZE` foi
adicionada à máscara de bordas para que a verificação de integridade confirme o
estado do player restaurado perfeitamente, aproveitando que a chamada
`SetWindowPlacement` (já existente no fluxo) é a responsável correta por restaurar
o estado maximizado de forma limpa, não precisando de manipulação de estilo prévia para desmaximização.

Fontes primárias verificadas: [lista do OBS 31.0.3](https://github.com/obsproject/obs-studio/blob/31.0.3/plugins/win-capture/window-capture.c)
e [visibilidade/comparação dos títulos](https://github.com/obsproject/obs-studio/blob/31.0.3/libobs/util/windows/window-helpers.c).

## INC-032 — Ajustes fragmentados e manutenção de fontes

**Sintoma.** O operador considera Ajustes/subjanelas complexos e a preparação
das fontes/plugins trabalhosa. Volume precisa ficar acessível sem ampliar
o painel principal ou perder configurações.

**Constatações de código.** A configuração estava distribuída entre diálogos.
Salvar ajustes gerais reconfigurava OBS mesmo sem mudar host/porta/senha.
Preparar áudio silenciava fontes já existentes; salvar um editor baseado em
estado antigo podia sobrescrever valores confirmados em outra ferramenta.
Essas constatações não provam a causa de todos os problemas físicos anteriores.

**Tratamento.** Categorias dentro da mesma janela, Volumes com acesso direto,
salvamento dos campos gerais sobre o estado atual e reconexão apenas quando
a conexão muda. Manutenção OBS verifica/completa itens ausentes, sem apagar
fontes, renomear cenas ou trocar Program. Estrutura de áudio existente não
é silenciada na preparação; só fontes novas começam silenciadas/desativadas.
Instalação explícita de plugins usa componentes prontos e verifica integridade.
Filtros/atraso ficam recolhidos na configuração de envio.

**Aceite de interface.** Em 07/10/2026, na revisão publicada `7a7697a`, o
operador respondeu: “Os ajustes ficaram ótimo!”. A organização foi aprovada;
não há confirmação individual de cada operação de manutenção/plugin/áudio.
Não recalculamos hashes do núcleo nem estendemos o aceite a outros cenários.

**Evidência/limite.** Testes Qt percorrem ações reais do controlador com OBS
simulado; cobrem dados persistidos, ganhos, preparação repetida e falha parcial.
Layout é renderizado em quatro escalas. Instalação real, disposição com dois
monitores e escuta das chamadas precisam de aceite desta revisão.

A primeira execução Windows encontrou relatório com contraste ruim e retorno
ao tamanho inicial depois do redimensionamento em 200%. A janela passa a ser
limitada antes da criação nativa, além da conferência após Show. O teste define
o tamanho do desktop FHD sintético antes de Show, como o teste do painel, em
vez de começar pelos 700 px numa área real do runner de 512 × 364. Mantém a
exigência de caber no FHD testado, sem retirar a escala que encontrou o problema.
Rótulos de manutenção permitem quebra sem expansão horizontal; os relatórios
definem fundo/texto. ZIP é validado pelo nome original do membro, pois o Python
normaliza barras invertidas ao ler o pacote no Windows.

**Aprendizado.** Navegar, consultar, reparar estrutura e mudar o roteamento são
ações diferentes. Uma consulta não deve interferir na reunião; completar o
que falta não implica reconfigurar fontes que já funcionam. Salvar só o estado
confirmado e explicar pendências reduz retrabalho sem remover verificações.

[Mapa/testes](settings-workspace.md), `tests/test_settings_workspace.py`,
`tests/test_settings_workspace_scale.py`, `tests/test_obs_maintenance.py` e
`tests/test_obs_plugins.py`.

## INC-030 — captura correta da segunda janela JWL

**Sintoma e impacto.** O OBS listava as duas janelas do JW Library com o mesmo
nome. Selecionar qualquer opção mostrava a interface do operador, não a saída
do Salão. Capturar a Tela 2 inteira introduzia risco de espelhamento infinito
quando o Zoom era apresentado nesse monitor; a proteção do app recusava essa rota.

**Causa verificada.** A captura padrão do OBS identifica a janela por
título/classe/executável, não pelo HWND entregue pelo app. Essas propriedades
não distinguiam as duas janelas. Na revisão anterior, a preparação também
dependia de título utilizável, embora o identificador JWL já aceitasse saída
sem título. A DLL existente da ponte Program alimentava prévia/câmera; ela
não criava uma fonte de entrada para essa janela.

**Solução.** Criamos a fonte independente **Meeting Assistant - JWL (HWND)**,
tipo `meeting_assistant_jwl_capture`. Ela reutiliza Windows Graphics Capture
do próprio OBS, via `libobs-winrt` e
`IGraphicsCaptureItemInterop::CreateForWindow(HWND)`. Valida HWND, PID,
geração dos processos, relação UWP, classe e papel do monitor. Captura a área
cliente em GPU, sem captura de monitor, sem transporte de pixels pelo Python
e sem áudio. Perda da identidade invalida a fonte; não há busca por título
como alternativa.

A preparação confirma vínculo nativo e dimensões antes de ativar a fonte.
A antiga **Meeting Assistant - JWL** é preservada e desativada apenas na cena
gerenciada. O worker redescobre o vínculo após reinícios. Corrigimos também
brechas que permitiam captura de monitor em simulação ou outra captura de
janela disfarçada de fonte segura. Áudio, câmera WhatsApp, ponte Program e
comandos protegidos de troca JWL/Zoom não foram alterados.

**Entrega e evidência.** Revisão entregue:
[`e9bf684`](https://github.com/eduardoveiga-py/meeting-assistant/commit/e9bf684aaa0b522c351691c2b1e5729909856012).
Componente [`jwl-capture-v1.1`](https://github.com/eduardoveiga-py/meeting-assistant/releases/tag/jwl-capture-v1.1),
compilado do código nativo `6655475b7e6cb28150d54abfb3d321755acb5c72`.
O script verifica hashes fixados antes de instalar. A suíte local teve
508 testes aprovados; [CI Windows](https://github.com/eduardoveiga-py/meeting-assistant/actions/runs/37680405899)
e [build nativo](https://github.com/eduardoveiga-py/meeting-assistant/actions/runs/37680405818)
passaram na revisão entregue. Esse número descreve a execução, não uma garantia
permanente do projeto.

**Aceite físico.** Em 07/10/2026, após atualizar e executar, o operador respondeu:
“Excelente! Funcionou perfeitamente!”. O ambiente declarado no histórico é
Windows 11 com dois monitores. Isso confirma o funcionamento relatado da nova
captura. Não foram enviados neste retorno versões exatas OBS/JWL, diagnóstico,
taxa de quadros nem resultados individuais de todos os cenários do roteiro.
Reinícios, desconexão de monitor e matriz completa JWL/Zoom continuam como
regressões operacionais, sem recalcular hashes do núcleo histórico.

**Aprendizado.** Uma lista com dois nomes iguais não oferece identidade
suficiente. Usar o handle já identificado resolve a ambiguidade na camada
certa. Preservar a barreira contra feedback é parte da solução: liberar captura
de monitor esconderia o defeito e reintroduziria o Zoom no envio à própria chamada.
Build, configuração aplicada e imagem correta no teste real são evidências
distintas. [Arquitetura, instalação e diagnóstico](jwl-hwnd-capture.md).

## INC-031 — atualização Git bloqueada por alterações locais

**Sintoma.** `git pull --ff-only` recusou avançar de `b94f988` para
`e9bf684`: alterações em `docs/decision-log.md` e
`services/obs_capture_safety.py` seriam sobrescritas. Outros módulos do
guardião, automação, vídeo e UI também estavam modificados.

**Causa e impacto.** O checkout continha trabalho local não commitado. O Git
protegeu esses arquivos; a atualização não ocorreu. No PowerShell, comandos
nativos em linhas seguintes podem continuar após uma falha do Git, levando
o operador a executar código antigo sem perceber.

**Solução.** Guardar alterações e arquivos não rastreados com
`git stash push --include-untracked`, conferir `$LASTEXITCODE`, atualizar
com fast-forward e iniciar somente após sucesso. O stash foi mantido como
backup, sem `reset --hard` e sem reaplicação automática sobre a captura nova.

**Evidência e limite.** O operador confirmou funcionamento após essa orientação.
O conteúdo do stash não foi coletado nem comparado; não declaramos essas
modificações integradas, inválidas ou descartadas.

**Aprendizado.** Atualização bem-sucedida exige conferir o resultado do Git.
Preservar trabalho local é obrigatório; reaplicar mudanças antigas em segurança
ou identificação de janelas exige revisão, não um `stash pop` automático.
[Procedimento atual](test-python-update.md).

## INC-001 — JW Library fechava na primeira abertura

**Sintoma.** JWL abria, carregava e fechava; abertura manual seguinte permanecia.
O operador reproduziu o problema pelo menu Iniciar, mas relatou sucesso nos
testes de abertura por comando PowerShell.

**Evidência.** Eventos 1000/1002 informaram JWLibrary.exe 15.9.36.0,
`twinapi.appcore.dll` e exceção `0xc000027b`. Isso identifica a falha
registrada pelo Windows, mas não demonstra sua causa.

**Tratamento e situação.** O código atual usa ativação do pacote por AUMID,
`explorer.exe shell:AppsFolder`, e observa a abertura. O histórico não comprova
que esse método elimina o crash da primeira execução. Abertura manual/por
comando foi um contorno relatado.

**Aprendizado.** Diferenciar falha do aplicativo externo de falha do coordenador.
Processo solicitado não significa aplicativo pronto; evitar reaberturas cegas.
Ver `services/meeting_launcher.py`.

## INC-002 — Windows+D, cloak e recuperação da saída

**Sintoma.** Após Windows+D a saída JWL só voltava ao focar/clicar no app, ou
voltava após demora. O operador corrigiu a indicação inicial “Ctrl+D” para
**Windows+D**.

**Tratamento.** Identificação da saída nativa, observação de minimização/cloak,
posição e exposição; recuperação com confirmação antes de retomar o sensor.
O retorno do operador confirmou a correção em etapas anteriores.

**Aprendizado.** Visibilidade Win32 isolada não comprova exposição no desktop.
Não reintroduzir tentativas contínuas de foreground nem confundir restauração
com roubo de foco. A política atual mantém o guardião periódico **somente com
automação ativa**; inicialização pausada e retorno explícito são casos distintos.
[Contrato histórico](validated-hall-contract.md).

## INC-003 — Texto do Ano acionava Mídias

**Sintoma.** Ativar automação ou restaurar após Windows+D deixava OBS em Mídias,
mesmo quando o telão exibia apenas o Texto do Ano.

**Tratamento e evidência.** Detector visual da saída JWL com referência
persistente de repouso, estabilização e suspensão durante troca de janelas.
Texto do Ano corresponde a Palco; mídia real corresponde a Mídias. O operador
confirmou início/fim de mídia e retorno ao Palco.

**Aprendizado.** Janela aberta, pixels não pretos ou restauração não significam
reprodução. Sensor e OBS devem compartilhar o caminho de comando validado.
Foto usada na cena Texto do Ano e calibração do sensor são operações distintas.
[Contrato](validated-hall-contract.md), [arquitetura JWL](architecture-jwl-secondary-window.md).

## INC-004 — altura do app e botões fora da tela

**Sintoma.** Em Full HD, a janela ultrapassava a área útil e botões de Ajustes
ficavam atrás da barra de tarefas. O monitor do Salão tinha menos espaço.

**Tratamento e evidência.** Rolagem nos ajustes; comandos compactos e prévia
adaptável na tela principal. O operador confirmou que ficou mais prático e
melhor após os ajustes. Mudanças posteriores ainda exigem regressão de layout.

**Aprendizado.** Dimensionar pela área útil em pixels lógicos e pelo DPI.
Resolução nominal Full HD não equivale ao espaço disponível para widgets.

## INC-005 — largura estourada na inicialização

**Sintoma.** Controles e mensagens expandiam o conteúdo além da janela e
aparecia rolagem horizontal. O operador confirmou uma correção anterior.

**Tratamento.** Distribuição flexível, colunas de comandos, quebra de mensagens
e redução de restrições de largura. Textos longos de status devem permanecer
dentro da janela, sem determinar seu tamanho.

**Aprendizado.** Medir widgets com fonte/emoji e escala reais do Windows;
conferir também status de inicialização, não só o estado ocioso.
[Revisão e teste](review-fixes-2026-10-03.md).

## INC-006 — cabeçalho desaparecia apesar dos testes

**Causa reproduzida.** Rótulos recebiam largura zero porque uma mola separada
absorvia o espaço restante. O subtítulo crescia em altura e consumia a prévia.
Testes de rolagem/botões/estado não verificavam texto efetivamente exposto.

**Correção.** Reservar espaço à coluna de título, indicador com altura natural,
intervalos menores em pouca altura e renderizações Qt nativas em quatro escalas.
A regressão reproduziu o defeito antes do patch.

**Aprendizado e limite.** “Widget visível” não significa texto legível.
Qt offscreen do Windows produziu glifos/métricas inadequados para esse ensaio;
imagens nativas passaram a integrar o CI. Aceite físico específico deste patch
não está registrado nesta conversa. [Análise completa](layout-header-fix-2026-10-03.md).

## INC-007 — segunda janela Zoom não encontrada

**Sintoma.** As duas janelas estavam abertas, mas o app dizia não encontrar
a secundária; o fluxo exigiu correções de descoberta.

**Tratamento.** Habilitar dois monitores no Zoom antes da reunião e identificar
processo, classes e papel das janelas, inclusive janela antes escondida.
O fluxo foi posteriormente confirmado pelo operador.

**Aprendizado.** Configuração do Zoom e descoberta pelo app são verificações
separadas. Título ou uma única classe histórica não bastam para todos os estados.
[Contrato](validated-hall-contract.md).

## INC-008 — retorno ao JWL falhava e Zoom era fechado

**Sintomas.** Zoom ia para frente, mas JWL não voltava, demorava muito ou a
janela secundária Zoom desaparecia e não podia ser usada novamente. Em outra
tentativa, a seleção voltava indevidamente ao Palco.

**Solução confirmada.** Manter ambas abertas, alternar prioridade e confirmar
exposição. Preservar geometria uma vez por ciclo; suspender sensor/guardião
durante Zoom e retorno; retomar após confirmação do JWL. O operador declarou
funcionamento e pediu proteção contra regressões.

**Aprendizado.** Fechar/ocultar uma janela não é uma troca reversível segura.
Sensor concorrente pode desfazer uma escolha do operador. Não declarar sucesso
pelo comando Win32 enviado. Checkpoint e contrato foram preservados; seu aceite
histórico não valida automaticamente alterações posteriores de política.
[Contrato e evidências](validated-hall-contract.md).

## INC-009 — vários participantes no Zoom secundário

**Sintoma.** O operador podia destacar mais de um participante na janela
principal, mas via somente um na secundária.

**Situação.** Não há confirmação neste chat de uma configuração ou implementação
que resolva isso. A captura JWL por HWND não altera a visualização do Zoom.

**Aprendizado.** Projetar/capturar o Zoom principal seria mudança de contrato
com ensaio próprio, preservando a exclusão do retorno no envio à chamada.
Não registrar esse requisito como concluído por causa do sucesso JWL.

## INC-010 — borda superior no JWL

**Sintoma.** Ao abrir o app surgia uma faixa superior na segunda janela, que
também contaminava a foto. O operador relatou relação com o guardião.

**Tratamento e evidência.** O guardião atual evita forçar `SW_SHOWMAXIMIZED`
numa saída UWP já em tela cheia: essa mudança pode alterar a área cliente
e expor desktop mesmo com retângulo externo correto. Inspeciona primeiro e
recupera somente uma saída não saudável. A regressão cobre abertura/reativação,
minimização, invisibilidade e cobertura. Os ajustes históricos foram seguidos
de confirmação do operador, sem revisão/diagnóstico detalhado daquela execução.
[Teste](../tests/test_guard_startup_preserves_fullscreen.py).

A foto também verifica área cliente, frame e coordenadas físicas do monitor
e preserva a imagem anterior quando há borda.

**Aprendizado.** Geometria externa correta não garante conteúdo cobrindo o monitor.
A nova fonte HWND não redimensiona JWL nem substitui essa verificação da foto.

## INC-011 — foto bloqueada por sobreposição falsa

**Sintomas.** Mensagens “outra janela sobre o JWL”, `Shell_SecondaryTrayWnd`
e “a ordem das janelas mudou”, mesmo com o Texto do Ano visível.

**Tratamento confirmado.** Verificação visual separada de hit-testing; travessia
de Z-order ancorada no HWND, incluindo UWP omitido por enumeração genérica.
A prévia da foto admite geometria inconclusiva de superfícies do shell,
mantendo bloqueio de outras janelas e confirmação humana. O operador confirmou
captura/salvamento após as correções.

**Aprendizado.** Geometria reportada pelo shell não prova pixels desenhados
sobre o JWL. Travessia precisa ser limitada e detectar mudança/destruição.
Essa exceção da **foto** não libera sobreposição no sensor nem captura de monitor.
[Foto e limites](yeartext-and-obs.md), `services/window_exposure.py`.

## INC-012 — foto salva não era aplicada ao OBS local

**Sintoma.** O app conseguia criar cenas e salvar foto, mas aplicação dizia
que era necessário ter OBS no computador.

**Causa tratada.** Um endereço de rede também pode pertencer ao próprio PC.
Reconhecimento atual verifica loopback, interfaces locais e resolução de nome;
caminho padrão ou `localhost` isolado não são critérios de instalação.

**Situação e aprendizado.** Correção implementada/testada; o histórico posterior
não fornece um aceite específico deste erro. OBS realmente remoto exige arquivo
acessível nele. Separar arquivo gravado de fonte aplicada e confirmada.
[Revisão](review-fixes-2026-10-03.md), `services/local_host.py`.

## INC-013 — WebSocket OBS só recuperava após reabrir

**Sintoma.** Credenciais inseridas manualmente não bastavam; reabrir o app
permitiu reconhecer OBS e cenas, e criar a estrutura.

**Situação.** Recuperação confirmada pelo operador; causa raiz daquele episódio
não demonstrada. A configuração atual usa worker serial, reconexão e estado
observado. Falha da captura JWL não deve derrubar conexão/áudio.

**Aprendizado.** Não concluir “senha errada” ou “OBS ausente” apenas pelo indicador.
Registrar fase e erro da conexão sem credenciais; confirmar operação real.

## INC-014 — câmera Windows 10 ausente no WhatsApp

**Evidência.** Compat DirectShow aparecia no OBS e no enumerador DirectShow,
mas não no Media Foundation/WhatsApp. `COMPAT_REGISTERED` não comprovava
compatibilidade com o cliente. NDI foi experimentado no histórico.

**Decisão.** Windows 11 x64 tornou-se requisito por pedido do operador.
Compat/DirectShow, NDI e tentativas Windows 10 foram removidos da árvore ativa;
usa-se a API de câmera virtual Media Foundation.

**Aprendizado.** Registro e formato aceito por um cliente não validam outro
enumerador. Este caso foi encerrado por mudança de requisito, não por correção
da câmera Windows 10. [Decisão](windows11-video-architecture.md).

## INC-015 — bridge/prévia pouco fluida

**Sintoma e medidas históricas.** Bridge próxima de 16,9 fps e, em revisão
seguinte, bridge a 30 fps com prévia perto de 11,5 fps.

**Tratamento.** Program bruto NV12, conexão persistente, canais separados para
prévia/câmera, leitor compartilhado, último quadro e renderer Qt de vídeo.
Removido caminho de screenshots JPEG/conversão RGB por quadro.

**Evidência e aprendizado.** Diagnósticos posteriores mostraram bridge 29,8 fps
e prévia 24,8 fps naquele ensaio. Quadro substituído em fila limitada não
equivale sozinho a erro de transporte; FPS de submissão Qt não mede recepção
remota. [Arquitetura](windows11-video-architecture.md).

## INC-016 — câmera nativa funcionou; recepção WhatsApp travava

**Evidência.** Operador confirmou câmera listada e vídeo em chamada Windows 11.
Depois encontrou CPU próxima de 100% com OBS, JWL, app, WhatsApp, Zoom e navegador.
Também havia pequenas travadas com câmera integrada.

**Situação.** A etapa da câmera foi explicitamente aceita. Saturação relatada
contribui para a hipótese de disputa por recursos; não há benchmark nem prova
de que explica todo travamento. O operador também confirmou áudio/vídeo em uso
real no computador do Salão.

**Aprendizado.** Prévia local correta não prova codificação/recepção remota.
Separar bridge, renderer, CPU, cliente e rede. Não prometer recursos mínimos
precisos sem medir a carga simultânea. [Diagnóstico](test-virtual-camera.md).

## INC-017 — PowerShell bloqueava scripts

**Sintoma.** `Unblock-File` não bastava quando a política proibia execução;
também apareceram mensagens de script não assinado.

**Procedimento.** Invocar o script conferido com
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1`.
A opção vale para esse processo, sem alterar a política global.

**Aprendizado.** Marca de origem do arquivo e política de execução são barreiras
distintas. Não prometer que desbloquear o arquivo resolve todos os casos, nem
ignorar uma política organizacional que impeça a execução.

## INC-018 — versões pycaw e Python incompatíveis

**Sintomas.** O intervalo `pycaw<2027,>=20240210` não incluía as versões
numéricas por data da biblioteca. Depois a venv Python 3.14.7 contrariava
o requisito `>=3.12,<3.13`.

**Correção confirmada.** Fixar `pycaw==20240210` e selecionar Python 3.12 x64.
O script verifica o ambiente, preserva venv incompatível em backup antes de
recriá-la e para se não encontrar o interpretador compatível.

**Aprendizado.** Verificar o esquema real de versionamento. Instalar dependências
na venv errada não corrige o requisito de Python; oferecer comando consistente
com o caminho de desenvolvimento. [Atualização](test-python-update.md).

## INC-019 — checksum divergente de DLL

**Sintoma.** Instalador nativo recusou `meeting-assistant-bridge.dll` com
“Artifact checksum mismatch”. A causa exata daquela cópia não foi demonstrada.

**Tratamento atual.** Pacotes e manifestos verificados; a captura JWL fixa
ZIP, DLL, instalador e origem do build. Assets JWL publicados são preservados;
mudança nativa exige nova tag/build/pins.

**Aprendizado.** Não remover verificação para instalar uma DLL divergente.
Código Python novo não atualiza binário já carregado; release, artefato e
manifesto precisam corresponder. Integridade não prova comportamento físico.
[Componente JWL](jwl-hwnd-capture.md).

## INC-020 — DLL em uso na atualização

**Sintoma.** `Copy-Item` não podia substituir
`MeetingAssistantMediaSource.dll` em Program Files porque outro processo a usava.

**Procedimento.** Atualizar componentes de câmera com app/OBS/clientes consumidores
encerrados, conforme o instalador. A fonte JWL tem instalação separada e exige
OBS fechado; DLL já correta é reutilizada.

**Aprendizado.** Verificação do pacote pode passar e instalação falhar depois.
Não anunciar câmera instalada apenas por ativação COM, nem forçar sobrescrita
de módulo carregado. Não atualizar componentes durante reunião.

## INC-021 — vídeo virtual sem áudio das mídias

**Sintoma.** Mesa chegava ao Zoom como microfone, mas JWL/VLC/navegador não eram
ouvidos remotamente porque câmera virtual transmite vídeo, não áudio.

**Solução confirmada.** Captura da mesa e dos aplicativos selecionados no OBS;
monitoramento para VB-CABLE; microfone correspondente no Zoom e WhatsApp.
O operador confirmou áudio/vídeo em reunião no Salão.

**Aprendizado e limite.** Excluir retornos das chamadas do envio à própria chamada.
Um cabo serve para o mesmo mix local; WhatsApp ouvir retorno Zoom exige segundo
mix/cabo e Audio Monitor. Esse perfil adicional não herda o aceite do primeiro.
Sinal analógico já misturado na mesa não pode ser separado com confiabilidade
por software. [Rotas](audio-routing.md).

## INC-022 — ícone amarelo/mudo no OBS

**Dúvida.** Tooltip “desativar mudo” foi interpretado como possível configuração
de envio. Mute, monitoramento e faixas são controles diferentes.

**Configuração.** Preparação cria fontes gerenciadas silenciadas; ativação validada
libera o envio. A rota local usa **Monitorar apenas (silenciar saída)**, excluindo
essas fontes das faixas Program; isso não é uma instrução para manter toda
entrada em mute. Conferir estado, medidores e escuta no destino.

**Aprendizado.** Nome de ação do tooltip descreve o que clicar fará. Ícone ou
medidor sozinho não comprova áudio no cabo virtual. [Rotas](audio-routing.md).

## INC-023 — cena de áudio e fontes em várias cenas

**Dúvida.** Fonte **MeetingAssistant - Áudio Zoom** aparecia em outras cenas
e junto da estrutura de áudio criada pelo app.

**Tratamento.** Barramento/cena de áudio compartilhado mantém fontes disponíveis
nas cenas visuais; não é necessário mover toda captura para Mídias. Preservar
inputs e conferir monitoramento/filtros, sem criar outra captura do mesmo sinal.

**Aprendizado.** Item de cena, cena aninhada e input de áudio são objetos distintos.
Reuso não prova duplicação; duas rotas ativas do mesmo sinal podem duplicá-lo.
Não apagar a estrutura apenas pelo nome repetido. [Rotas](audio-routing.md).

## INC-024 — envio remoto baixo com fader em 100%

**Tratamento implementado.** Ganho por fonte de 0 a 18 dB, seguido de limitador
a −3 dB; leitura de confirmação dos filtros. **Volumes → Salvar volumes**
altera somente ganhos editados, sem refazer a rota.

**Evidência e limite.** Código e testes verificam filtros/aplicação. Não há
medição remota suficiente para declarar nível ideal ou ausência de distorção.

**Aprendizado.** Fader em 100% não impede ganho adicional por filtro.
Subir em passos pequenos e ouvir no receptor; ganho também eleva ruído.
Limitador contém picos, mas não recupera entrada já distorcida.
[Volume e filtros](audio-routing.md).

## INC-025 — configuração confusa e Aplicar desabilitado

**Sintoma.** Fontes criadas e confirmações marcadas, mas ativação bloqueada.
Havia pendências de dispositivos não explicadas e escolhas descartadas ao
atualizar listas. Enumeração comparava `AudioDeviceState.Active` com inteiro.

**Correção.** Comparar o valor do Enum, separar **Envio / Volumes / Ajuda**,
consulta somente de leitura, preservar escolhas ainda disponíveis e tornar
pendências visíveis. Ativar envio aponta o campo ausente; ganhos têm ação própria.

**Aprendizado e limite.** Mocks devem representar os tipos reais das bibliotecas.
Configurar volume não deve recriar/silenciar o envio. Segundo cabo/mix-minus
continuam requisitos do perfil com retorno; ensaio físico dessa revisão permanece
pendente. [Decisões](decision-log.md), [roteamento](audio-routing.md).

## INC-026 — ruído da mesa somente no OBS

**Evidência.** O operador relatou ruído na fonte OBS, ausente quando a entrada
era usada diretamente como microfone Zoom/WhatsApp.

**Situação.** Não há diagnóstico físico conclusivo nem retorno confirmando
remoção do ruído. Instalar Audio Monitor ou mudar ganho não prova correção.
O sucesso anterior do VB-CABLE não invalida esse relato posterior.

**Aprendizado.** Isolar entrada, formato, filtros e rotas num teste comparável,
registrando configuração antes/depois. Não aplicar supressão indiscriminada
nem atribuir o ruído ao cabo/mesa sem evidência. Manter este incidente aberto.

## INC-027 — Mic Zoom não fazia nada

**Falhas reproduzidas.** Clique só consultava quando estado era desconhecido;
cache podia decidir errado; consulta descartava clique; busca ampla confundia
vídeo/áudio. Correção inicial ainda bloqueava microfone reconhecido quando
RuntimeId não estava disponível.

**Correção e aceite.** Worker lê estado atual, identifica um único microfone
próprio por processo/janela/papel, envia uma ação e confirma. RuntimeId é opcional
para deduplicação, sem fundir candidatos desconhecidos. O operador confirmou
abrir/silenciar após a correção.

**Aprendizado.** Testar clique Qt até backend, incluindo propriedades ausentes
e tipos reais; cache de apresentação não decide comando. Não repetir ação
quando envio teve resultado incerto. [Análise](zoom-microphone-control.md).

## INC-028 — Mic Zoom funcionava, mas demorava

**Evidência.** Operador relatou cerca de cinco segundos para abrir/silenciar.
O código fazia descoberta repetida e recriava worker/COM; não houve medição
detalhada das fases no PC naquele ensaio.

**Otimização implementada.** Worker COM MTA persistente, referência validada,
busca filtrada pelo processo e confirmação imediata; diagnóstico por fase.

**Aprendizado e limite.** Manter referência COM na thread proprietária e
revalidar identidade/estado. Menos buscas em teste simulado não garante latência
real menor; retorno físico da otimização ainda está pendente.
[Teste de tempos](zoom-microphone-control.md).

## INC-029 — Controle Inteligente de Aplicativos bloqueou EXE

**Sintoma.** Windows informou não conseguir verificar o fornecedor de
`MeetingAssistant.exe` instalado. Não há aceite registrado de uma distribuição
assinada posterior que resolva esse bloqueio.

**Situação e aprendizado.** Compilação bem-sucedida não significa software
reconhecido pela política de confiança do Windows. Assinatura/distribuição e
ensaio em máquina nova são uma etapa separada. Manter registrado no plano da
futura release; não documentar desativação da proteção como correção do app.
O fluxo de teste atual permanece Python, sem novo instalador neste lote.

## Regras de manutenção extraídas desses casos

1. Identificar janelas por processo, geração e papel; título é descrição,
   não identidade. Verificar imagem/resultado além de configuração enviada.
2. Manter sensor, recuperação de janelas, fonte OBS, bridge, câmera e áudio
   com responsabilidades separadas. Uma correção de entrada não deve alterar saída.
3. Não enfraquecer barreiras de feedback, mix-minus ou confirmação para fazer
   uma preparação passar. Exceções limitadas precisam de evidência e escopo.
4. Testar integração de cliques, tipos ausentes, reconexão e falhas parciais.
   Layout exige geometria/texto e renderização nativa, além de estado lógico.
5. Código, CI, build, instalação, API e ensaio físico são níveis diferentes
   de evidência. Atualizar pendências por cenário e revisão; não herdar aceites.
6. Preservar trabalho local, dados e fontes do operador. Não sobrescrever
   assets nativos fixados nem recalcular baseline para esconder uma alteração.
7. Oferecer Git + Python + DLL pronta no desenvolvimento. Atualizador do
   executável e novo instalador são entregas separadas e posteriores.

## Como acrescentar outro incidente

Manter o ID, mesmo quando o caso reabrir. Registrar data do relato, revisão
entregue e revisão efetivamente diagnosticada quando disponível; ambiente,
sintoma/impacto, evidência, causa demonstrada ou hipótese, solução, teste/retorno,
limites e aprendizado. Usar links para decisões, código e roteiro.
Não incluir senhas, links privados, dados de participantes ou dumps de ajustes.

Após “funcionou”, delimitar exatamente o que foi confirmado. Uma correção
posterior não apaga falhas anteriores, e uma implementação nova não encerra
um incidente apenas porque seus testes simulados passaram.
