# Testes do lote: áudio, atalhos e organização

Implementado em módulos separados, após o operador aprovar os três testes de telas
no commit `02094d8`. O núcleo protegido não foi alterado. Testes automatizados não
substituem a escuta real com mesa/Zoom. Nenhum driver é instalado ao abrir o app.

## Atualizar

Feche somente o Meeting Assistant. No PowerShell:

```powershell
cd C:\MeetingAssistant\meeting-assistant
git branch --show-current
git pull --ff-only
.\scripts\setup-dev.ps1
.\scripts\run-dev.ps1
```

A branch deve ser `feature/meeting-launch-zoom-hall`. Se houver alterações locais
ou o pull falhar, envie a mensagem; não use reset nem descarte arquivos.

## Teste A — interface e atalhos (sem mesa e sem segundo monitor)

1. Abra Ajustes. No topo estão Áudio, Observar mídia e Calibrar Texto do Ano.
   Os dois últimos saíram da tela principal. Não é necessário recalibrar o que já funciona.
2. Volte à tela principal e aperte F1. Confira a lista.
3. Com OBS aberto, teste F2/F3/F4: Fundo, Palco, Mídia. Teste F6: automação;
   F7: pausa a automação e seleciona Palco. F9: Verificar. F10: Ajustes.
4. Dentro de Ajustes, aperte F3: não deve disparar Palco. Com OBS/Zoom em foco,
   as teclas devem continuar pertencendo ao programa em foco.
5. Uma tecla mantida pressionada não repete a ação. Em notebook, talvez seja necessário Fn.
6. F8 usa a função existente Iniciar reunião: só teste quando quiser abrir os aplicativos.
7. Se o segundo monitor ainda estiver conectado, teste F5 duas vezes: Zoom → Salão → JWL.
   Sem ele, deixe este item para o próximo ensaio físico.

| Tecla | Ação |
| --- | --- |
| F1 | Ajuda dos atalhos |
| F2 | Fundo / Texto do Ano |
| F3 | Palco |
| F4 | Mídia |
| F5 | Zoom → Salão / voltar ao JWL |
| F6 | Ativar / pausar automação |
| F7 | Cena segura → Palco |
| F8 | Iniciar reunião |
| F9 | Verificar |
| F10 | Ajustes |

Esta etapa não registra atalhos globais nem altera atalhos nativos do Windows.
Remapeamento e modo global permanecem pendentes.

## Teste B — preparar áudio (não exige segundo monitor)

Faça fora de uma reunião real. Para certificar o som da mesa, a entrada física deve
estar conectada. Anote antes qual microfone o Zoom está usando, para restaurá-lo.

1. Instale [VB-CABLE pelo site oficial](https://vb-audio.com/Cable/), usando o instalador
   apropriado ao Windows e as permissões solicitadas. Reinicie conforme instrução do fabricante.
   Esta versão do app oferece o link; não instala o driver automaticamente.
2. No OBS: Configurações → Áudio → Avançado → Dispositivo de monitoramento = **CABLE Input**.
3. Nas Propriedades avançadas de áudio do OBS, deixe as fontes antigas com
   **Monitoramento desligado**. O app bloqueia ativação se encontrar outra fonte monitorada;
   não muda suas fontes pessoais automaticamente.
4. No Zoom: Configurações → Áudio → Microfone = **CABLE Output**. Alto-falante = a saída
   física já usada no Salão. A câmera continua **OBS Virtual Camera**.
5. Mantenha a reprodução local de JWL/VLC/navegador na saída física atual. Não selecione
   CABLE Input como saída padrão geral do Windows: o cabo é o destino da mistura do OBS.
6. Abra Ajustes → Áudio da mesa e das mídias → Zoom. Abra também JWL/VLC/navegadores que
   pretende usar. Clique **Preparar / atualizar listas — silencia envio**.
7. Escolha a entrada física da mesa. Não usamos “Padrão” para evitar mudança silenciosa
   de dispositivo. Escolha a janela de cada aplicativo desejado; deixe os outros sem seleção.
   Se faltar um app, abra sua janela e prepare novamente. Captura por aplicativo requer
   suporte do OBS/Windows; não há fallback para capturar todo o áudio do computador.
8. Confirme as três caixas somente após conferir o caminho real:
   OBS CABLE Input; Zoom CABLE Output/alto-falante físico; entrada da mesa sem retorno
   do Zoom e sem uma segunda cópia das mídias.
9. Clique **Aplicar seleção e ativar envio ao Zoom**. O app confirma fontes/monitoramento
   no OBS, mas não certifica que alguém ouviu o som. Faça o Teste C.

O app cria `Meeting Assistant - Áudio Zoom`, contendo a entrada da mesa e quatro fontes
independentes de captura por aplicativo. Essa cena é incluída em Fundo, Palco e Mídias.
Somente as fontes selecionadas são habilitadas e monitoradas. A cena Program e as janelas
JWL/Zoom não são trocadas por esta configuração. OBS salva fontes, seleção e ativação;
fechar o Meeting Assistant **não silencia o áudio**. Preparar novamente silencia as fontes
criadas pelo módulo; ative novamente depois de conferir.

Se a mesa já inclui o áudio de mídia no sinal enviado ao notebook, não ative também sua
captura por aplicativo: isso duplica o som. Se ela inclui o retorno do Zoom, ajuste uma saída
separada da mesa que exclua esse retorno (mix-minus) antes de ativar. O app não consegue
separar os sons que já chegaram misturados pela entrada física.

## Teste C — escuta remota (mesa + outro participante)

Use outro dispositivo com fones, preferencialmente em outro ambiente. No notebook,
confira os medidores do OBS e ajuste volumes no mixer do OBS, sem saturar.

1. **Voz:** fale no microfone da mesa; o participante remoto deve ouvir uma única voz limpa.
2. **JWL:** reproduza um vídeo e depois uma música; confirme som remoto e local.
3. **VLC / Chrome / Edge:** teste cada um que selecionou. Troque título/aba. O navegador
   selecionado pode enviar som de outras abas; feche as que não devem ser ouvidas.
4. **Voz + mídia:** confirme equilíbrio, sem eco ou duplicação.
5. **Retorno:** o participante remoto fala; ele não deve ouvir a própria voz voltando.
6. **Trocas de vídeo:** alterne Fundo/Palco/Mídia; o som deve continuar. Com segundo monitor,
   faça também Zoom → Salão → JWL. Isso não deve reenviar o áudio do participante.
7. **Silêncio:** em Ajustes → Áudio, clique **Silenciar envio do app**. A mistura para o Zoom
   deve parar. Para retornar ao funcionamento anterior, selecione no Zoom a entrada física
   da mesa que você anotou. O áudio local continua pela ligação existente.
8. Depois de aprovado, reinicie OBS/app/Zoom e confira os dispositivos e a escuta novamente.
   Não considere a persistência no OBS como prova de que o cabo e os dispositivos estão corretos.

Se o Zoom cortar música, revise suas opções de áudio original/música antes de concluir
que a captura falhou. Não habilite áudio original indiscriminadamente sem testar eco.

## Retorno a enviar

```text
Versão/commit:
A — Interface e atalhos: OK / falha (qual tecla/tela?)
B — Preparação: OK / mensagem exata
Entrada da mesa selecionada:
C1 — Voz: OK / falha
C2 — JWL: OK / falha
C3 — VLC / Chrome / Edge: resultado de cada app usado
C4 — Voz + mídia: OK / duplicação / volume
C5 — Participante ouve a própria voz? Sim / Não
C6 — Trocas de cena: OK / corte de som
C7 — Silenciar e voltar à entrada antiga: OK / falha
C8 — Reinício: OK / falha
Segundo monitor disponível? Sim / Não
```

Se aparecer eco forte, silencie primeiro o microfone no Zoom e volte à entrada antiga.
Se um aplicativo não aparecer ou não capturar áudio, envie nome/versão e a mensagem;
não selecione Zoom ou captura global como substituição.

## Limites deste lote

- Monitoramento do OBS e dispositivos Zoom são conferidos manualmente na própria tela de orientação.
- Sem instalação automática de VB-CABLE, controle de volumes no app ou medidores no app ainda.
- A captura por processo pode não funcionar com todos os aplicativos/versões, especialmente UWP;
  o teste real do JWL é obrigatório. O módulo não usa ApplicationFrameHost genérico como substituto.
- Preparação de áudio usa a fila serial do OBS; ajustes permanecem abertos até o resultado.
- A preparação não certifica microfone, câmera, rede ou conteúdo de uma reunião.

Referências técnicas: [captura por aplicativo](https://obsproject.com/kb/application-audio-capture-guide),
[OBS em videochamadas](https://obsproject.com/kb/video-call-streaming-tutorial),
[API OBS WebSocket](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md).
