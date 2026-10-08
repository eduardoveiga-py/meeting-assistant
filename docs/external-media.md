# Mídia externa — apresentação e controles

O botão **Mídia Externa** escolhe uma janela aberta de Chrome, Edge, VLC ou
player Windows suportado. O OBS usa **Meeting Assistant - Mídia Externa** e
**Meeting Assistant - Player**, com captura de janela separada do JWL.
Não se usa captura de monitor nem outra captura de som nesse vídeo.

## Operação

1. Abra/carregue a mídia. No navegador, deixe o vídeo na aba visível da janela
   que será escolhida. Retorne do modo Zoom → Salão, se ativo.
2. Clique **Mídia Externa**, selecione a janela e clique **Apresentar**.
3. Surge um popup **Mídia externa — Chrome/Edge/VLC/Player** no monitor principal.
   Durante a preparação, os controles de reprodução ficam desabilitados; Parar
   ainda permite cancelar. Aguarde a apresentação confirmada no Salão e no OBS.
4. Use **Reproduzir**, **Pausar**, **Maximizar** e **Parar mídia** no popup.
   Chrome e Edge também oferecem **Tela cheia do vídeo**.
5. **Parar mídia**, o X do popup ou o botão de retorno do painel solicitam a
   mesma operação. Aguarde **Retornando…**: interromper mídia, restaurar Program,
   disposição do player e saída JWL. O popup fecha após confirmar o retorno.

O popup é independente dos Ajustes e não ocupa outro espaço no painel principal.
O app permanece no primeiro monitor. O player recupera tamanho/estado original,
inclusive minimização; se sua posição salva era no Salão ou ficou fora da área
útil, o retorno ajusta essa posição ao monitor principal. Não fecha o player,
a aba ou a reunião. Uma falha de retorno mantém **Repetir retorno** disponível.

## Cessão do monitor e proteção durante a apresentação

O retorno seguinte de `e072427` também foi negativo: a mesma mensagem e nenhuma
janela movida para a segunda tela. Sem diagnóstico atual, a causa específica do
PC não foi confirmada. A revisão encontrou/reproduziu outra falha: o estilo
salvo do player reaplicava WS_MINIMIZE/WS_MAXIMIZE após pedir restauração.
A nova candidata espera o estado normal/visível antes de ceder JWL; lê o estilo
atual e altera somente a borda. Snapshot original permanece reservado ao retorno.
O CI também exercita Win32 real com janelas de teste, em processo separado.

O retorno físico de `7a5f7db` falhou: o player chegou à frente brevemente e o
app abortou por não confirmar sua exposição. Demover TOPMOST uma vez não
assegurou a cessão da janela UWP. Essa candidata não foi aceita fisicamente.

A nova candidata identifica a saída secundária JWL por HWND/classe/processo,
resolvendo o frame e seu CoreWindow quando necessário. Valida a relação entre
PID do ApplicationFrameHost e PID filho JWLibrary, sem escolher pelo título.
Guarda uma única disposição original por ciclo. Uma referência ao frame validado é retida para o retorno quando a saída oculta deixa de aparecer temporariamente no inventário UIA; é descartada se a identidade mudar ou o ciclo terminar.

Durante mídia externa, **somente a saída secundária JWL é ocultada
temporariamente** por pedido Win32 assíncrono. Seu processo/handle permanecem
abertos; sua borda, posição e tamanho não são modificados. A janela JWL do
operador permanece disponível. Guardião e sensor ficam suspensos desde a
seleção até o retorno confirmado, independentemente da automação solicitada.

A exposição do player é confirmada antes e depois da preparação OBS e observada
a cada 350 ms em worker, sem consultas Win32 na GUI. Se JWL reaparecer, o ciclo
refaz a cessão. Posição/minimização/prioridade do player são recuperadas sem
ativação periódica do foreground. Janela trocada/fechada ou exposição que não
se recupera causa retorno com erro explícito. Não se oculta outra janela por
estar cobrindo o player. Ao parar ou encerrar o app, a visibilidade/prioridade
JWL é restaurada; o retorno existente confirma a saída antes de retomar sensor.

## Comandos por aplicativo

| Controle | Chrome/Edge | VLC e outros players |
| --- | --- | --- |
| Reproduzir/Pausar | Botão acessível do vídeo na aba escolhida, lendo ação atual | Botão acessível do player, lendo ação atual |
| Parar mídia | Pausar vídeo antes de retornar | Acionar Stop/Parar do player antes de retornar |
| Maximizar | Preencher o monitor com a janela selecionada | Preencher o monitor com a janela selecionada |
| Tela cheia do vídeo | Invocar o botão de tela cheia do vídeo e verificar sua ação inversa | Use Maximizar; o app não adota outra janela de fullscreen do VLC |

Reproduzir/Pausar são idempotentes: não alternam novamente um vídeo que já
está no estado pedido. O comando se limita à identidade da janela escolhida e,
no navegador, ao documento da aba visível, incluindo seus players embutidos.
Mais de um controle de reprodução compatível é ambíguo e não recebe comando.

Não se enviam teclas multimídia globais, Espaço ou F por tentativa. No YouTube,
F é um atalho do player; Espaço pode ativar o botão focado. Isso não é um
contrato genérico do Chrome. O popup usa UI Automation/ação acessível e consulta
o estado depois. Se a página ou player não expõe esse controle, informa a
limitação e mantém a apresentação disponível; não aciona outro app/aba.

Os controles usam um processo Python isolado, com COM próprio, cancelamento e
prazo total de 5 s; consultas travadas não bloqueiam Qt nem ficam executando
após o retorno. Um comando em andamento é concluído/cancelado antes de Parar.
O app não instala extensão de navegador, ativa depuração remota nem muda
atalhos do Windows. `pywinauto` já é dependência do projeto; não há DLL nova.

Ao retornar, sai da tela cheia solicitada pelo popup. Se parar/pausar não for
confirmado, ainda tenta restaurar JWL/Program e deixa **Aviso** no painel:
confira a reprodução no aplicativo. Retorno de janela não comprova silêncio.
O som continua nas fontes identificadas configuradas em **Áudio → Envio**;
ganhos, barramento e mutes não são reconfigurados por esse módulo.

## Teste físico da candidata

Faça fora da reunião, primeiro com automação pausada:

1. JWL e OBS prontos. Carregue um vídeo no Chrome e minimize o navegador.
   Selecione-o em Mídia Externa. Confira popup no primeiro monitor, Chrome no
   segundo e imagem correta no preview/câmeras. Aguarde pelo menos 30 s e
   clique em outras janelas no primeiro monitor: JWL não deve reaparecer à frente.
2. Use Reproduzir, Pausar e Reproduzir novamente. Confira imagem e áudio tanto
   no Salão quanto nas chamadas. Teste Maximizar e Tela cheia do vídeo no Chrome.
   Mantenha o popup acessível no primeiro monitor durante a tela cheia.
3. Clique Parar mídia: reprodução interrompida, player no primeiro monitor em
   sua disposição anterior, JWL à frente no segundo e OBS na cena anterior.
   Popup fechado, botão Mídia Externa pronto e estado da automação preservado.
4. Repita dois ciclos com automação ativa. Aguarde 30 s a cada apresentação;
   sensor não deve trocar Program, e guardião não deve cobrir o player.
5. Repita com VLC: Reproduzir, Pausar, Maximizar e Parar. Seu botão Parar deve
   interromper o player. Repita com Edge se for usado no Salão.
6. Teste Cancelar no seletor, Parar durante preparação, X do popup e Parar
   enquanto um comando responde. Nada deve ficar preso no modo externo.
   Fora do modo externo, confira Forçar JWL, Windows+D e um ciclo Zoom/JWL.

Se falhar, envie **mensagem exata**, aplicativo, site/player usado (ex.: YouTube
ou vídeo jw.org, sem link privado), se estava minimizado, estado da automação e
horário. Em **Ajustes → Diagnóstico**, `external_media_task` registra
`native_show`, `native_confirm`, `native_monitor`, `native_control:play/pause/...`,
`native_stop_media` e `native_restore`, com resultado, tempo e exposição/cessão
JWL. Monitoramento saudável não gera evento a cada tick. Não registra títulos,
URLs ou nomes de participantes. Telemetria sincronizada permanece opcional.

Na mensagem, `[PLAYER_RESTORE]` indica restauração não confirmada;
`[PLAYER_POSITION]`, posição/tamanho; `[JWL_HANDOFF]`, cessão JWL;
`[PLAYER_CLOAKED]`, cloaking Windows; `[PLAYER_EXPOSURE]`, cobertura por outra
janela; `[WINDOW_API:etapa]`, falha da chamada nativa antes da confirmação.
Se persistir, abra **Ajustes → Diagnóstico → Exportar diagnóstico…** logo após
a tentativa e envie o ZIP da sessão. Não precisa ativar envio remoto nem captura
de tela. O diagnóstico registra etapa, flags, posição e classes das janelas que
cobrem os pontos consultados, sem títulos/URLs. Confira também `git rev-parse
--short HEAD` para identificar o código realmente executado.

Testes automatizados verificam cliques Qt, workers/processos reais, OBS/Win32
simulados, cessão que se perde depois da confirmação, cancelamento, restauração
assíncrona e DPI. CI Windows não comprova Chrome/VLC reais em dois monitores.
A apresentação e esses controles ainda exigem o aceite físico acima.

## Recuperação e limites

| Situação | Ação |
| --- | --- |
| Saída JWL não identificada | Use Forçar JWL e confira o monitor antes de selecionar |
| OBS não conectado/local confirmado | Confira Ajustes → OBS e vídeo → Conexão |
| Nome Player ocupado por outro tipo de fonte | Confira o nome indicado; o app não apaga fonte pessoal |
| Títulos duplicados no OBS | Deixe títulos diferentes; selecionar a linha certa não elimina a ambiguidade |
| Controle acessível indisponível/ambíguo | Deixe um vídeo visível na aba escolhida; informe o site/player se persistir |
| Player perde exposição e não recupera | Aguarde retorno; envie a mensagem e diagnóstico |
| Aviso de parada/pausa | Confira se o aplicativo continua emitindo áudio |
| Retorno JWL/player não confirmado | Use Repetir retorno; automação continua suspensa |

A captura OBS padrão ainda usa título para selecionar a janela. Não abra uma
janela duplicada nem troque de aba/conteúdo durante a apresentação; retorne e
selecione novamente. Não acrescente captura de monitor à cena externa.

Referências primárias: [atalhos YouTube](https://support.google.com/youtube/answer/7631406),
[ShowWindowAsync](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-showwindowasync),
[WINDOWPLACEMENT](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-windowplacement)
e [UI Automation/Invoke](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-invoke-control-pattern).
