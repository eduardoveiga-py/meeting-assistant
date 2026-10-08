# Mídia externa — player ou navegador

A apresentação usa **Meeting Assistant - Mídia Externa** e a fonte
**Meeting Assistant - Player**, separadas da captura nativa JWL. O botão
**Mídia Externa** permite escolher VLC, players Windows suportados, Chrome ou
Edge já abertos. Não captura a tela inteira nem abre automaticamente uma mídia.

## Operação

1. Abra a mídia no player ou navegador. Deixe o conteúdo carregado.
2. Retorne do modo Zoom → Salão, se ativo.
3. Clique **Mídia Externa**, selecione a janela e clique **Apresentar**.
4. Confira a imagem no segundo monitor e no preview OBS.
5. O botão muda para **Parar mídia**. Clique para retornar; aparece
   **Retornando…** até confirmar a visibilidade do JWL.

O player pode estar minimizado: o app confirma OBS, guarda a disposição atual
e restaura a janela antes de selecioná-la na captura. O título é relido depois
do posicionamento. Durante seleção, apresentação e retorno, guardião e sensor
ficam suspensos. A automação solicitada pelo operador permanece registrada
e só volta a agir quando o JWL confirma a saída.

O app confere exposição em cinco pontos internos, geometria, minimização e
cloaking do player. A saída JWL cede prioridade temporariamente, sem modificar
bordas/tamanho. Recusa de exibição causa tentativa de retorno; apenas mover
a janela não é anunciado como sucesso. A conferência se repete após preparar OBS.

**Cancelar mídia** fica disponível durante a preparação. **Retornando…**
indica operação em andamento. Uma falha oferece **Repetir retorno**. A posição
e o estado original do player, inclusive minimização, são restaurados;
o aplicativo permanece aberto.

O som continua nas fontes de aplicativos configuradas em **Áudio → Envio**.
Selecione o aplicativo que reproduz a mídia nessa configuração e confira
a escuta remota. A fonte de vídeo Player não acrescenta outra captura de som.

## Mensagens e recuperação

| Mensagem/situação | Ação |
| --- | --- |
| OBS desconectado/local não confirmado | Confira **Ajustes → OBS e vídeo → Conexão**; a janela não é movida nessa falha |
| Nome Player ocupado por outro tipo | Confira a fonte/cena indicada no OBS; o app não substitui nem apaga a fonte pessoal |
| Duas janelas com o mesmo título | Feche a duplicada ou altere seu título; selecionar a linha correta não elimina a ambiguidade do OBS |
| Player fechou/mudou de processo ou título | Deixe a mídia carregada e selecione novamente; não há substituição automática por outra janela |
| Program mudou durante a preparação | A mudança feita no OBS é preservada; tente novamente a partir da cena desejada |
| Retorno JWL não confirmado | Confira o monitor e solicite nova tentativa pelo botão; automação permanece suspensa até confirmar |
| Player não ficou visível à frente do JWL | Aguarde o retorno e tente novamente; envie diagnóstico se persistir |
| Player não confirmou disposição anterior | JWL ainda recebe pedido de retorno; use Repetir retorno para concluir a restauração do player |

Cancelar no seletor não modifica OBS/janelas. Cancelar durante preparação
aguarda o resultado em andamento e desfaz usando a cena/disposição confirmadas.
Em falha, o app tenta restaurar o player e o JWL; o motivo original permanece
na mensagem final. Uma falha de retorno continua explícita.

Não coloque captura de monitor na cena externa. A captura padrão de janela
do OBS usa título; janelas com título igual continuam bloqueadas, mesmo de
processos diferentes. A fonte JWL por HWND e suas proteções não mudaram.

## Teste da correção candidata

Faça fora da reunião:

1. OBS e JWL abertos, automação pausada. Abra um vídeo no VLC, minimize-o,
   clique **Mídia Externa**, escolha VLC e apresente. Confira imagem no Salão/OBS.
2. Clique **Parar mídia**. Confira Program anterior, disposição anterior do VLC
   (inclusive minimização) e JWL visível. Repita com automação ativa:
   o guardião não deve cobrir o player e a automação não deve trocar Program.
   Faça dois ciclos em cada estado e confira que o botão volta a Mídia Externa
   depois de concluir o retorno.
3. Repita com conteúdo carregado no Chrome ou Edge. Teste Cancelar no seletor
   e retorno solicitado durante a preparação. Não deve ficar preso no modo externo.
4. Confira áudio no Salão e nas chamadas, sem outra captura de som/ganho alterado.

Se houver erro, envie **a mensagem exata**, o aplicativo escolhido, se estava
minimizado, estado da automação e horário. Em **Ajustes → Diagnóstico**, o log
registra estados e resultado das ações `external_media_task`, incluindo
`native_show`, `native_confirm` e `native_restore`: exposição/ativação e
confirmação de posição, minimização e prioridade. Não registra títulos,
URLs ou conteúdo do player. Telemetria sincronizada continua opcional.

Os testes automatizados usam workers reais com OBS/Win32 simulados. Não substituem
dois monitores, imagem capturada ou escuta nas chamadas.
