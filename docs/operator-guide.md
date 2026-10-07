# Guia do operador — Meeting Assistant

Atualizado em 07/10/2026. Operação em Windows 11 x64, com OBS, JW Library,
Zoom e WhatsApp. O [histórico de incidentes](incident-history.md) registra
quais testes foram confirmados e o que permanece pendente.

## Preparar fora da reunião

1. Atualize pelo [fluxo Git/Python](test-python-update.md). Para instalar a nova
   captura JWL, feche OBS e o app antes de executar o script.
2. Abra OBS/JWL e deixe o Windows em modo **Estender**. Habilite a saída secundária
   do JWL e selecione a **Tela do Salão** nos ajustes do app.
3. Confira host, porta e senha do WebSocket do OBS. Aguarde a conexão indicada pelo
   app antes de preparar fontes.
4. Em **Ajustes → OBS e vídeo → Fontes**, verifique e complete as fontes; use
   **Preparar captura JWL** para vincular novamente a janela em Mídias.
   Requer OBS 31.0.3+ e Direct3D 11. A fonte
   **Meeting Assistant - JWL (HWND)** deve mostrar a saída do Salão, mesmo com
   nomes iguais no OBS. [Instalação e diagnóstico](jwl-hwnd-capture.md).
5. Em **OBS e vídeo → Texto do Ano**, capture/confirme a foto e seu ano quando
   faltar ou precisar atualizar. Salvar a foto **não recalibra o sensor**.
6. Em **Ajustes → Áudio → Envio**, confira o perfil e os dispositivos.
   Se a estrutura já estiver funcionando, consultar a tela não exige recriá-la.
   **Completar fontes de áudio** preserva fontes existentes e cria somente
   o que falta, com fontes novas silenciadas. Use **Ativar envio** para aplicar
   uma seleção de dispositivos, após conferir o roteamento.
7. No Zoom, selecione **OBS Virtual Camera** e o microfone virtual correspondente.
   No WhatsApp, selecione **Meeting Assistant** e o microfone virtual do seu perfil.
   Faça uma chamada curta: a prévia do app não comprova recepção remota.

Configure links/dispositivos antes da reunião. Dados de conexão e fotos ficam
na pasta privada do usuário; não os publique junto do projeto.

[Mapa completo de Ajustes e manutenção do OBS](settings-workspace.md).

## Áudio: escolher o perfil

| Perfil | Microfone Zoom | Microfone WhatsApp | O que o WhatsApp recebe |
| --- | --- | --- | --- |
| Mesa e mídias nos dois aplicativos | Cabo A Output | Cabo A Output | Mesa e mídias locais |
| Incluir participantes do Zoom no WhatsApp | Cabo A Output | Cabo B Output | Mesa, mídias e retorno Zoom |

No OBS, o monitoramento global aponta para **Cabo A Input**. O perfil com
retorno Zoom exige outro cabo e o plugin **Audio Monitor do Exeldro**.
Use os nomes realmente instalados no seu computador; os endpoints de reprodução
(Input) e gravação (Output) têm papéis diferentes.

- Mídias e som recebido do Zoom seguem para a saída física do notebook/mesa.
- O retorno do WhatsApp começa silenciado; o botão **WhatsApp** controla apenas
  o som recebido desse aplicativo.
- O áudio enviado ao Zoom exclui seu próprio retorno. O retorno WhatsApp não
  deve entrar nos mixes enviados.
- A entrada da mesa precisa excluir sinais que já são capturados separadamente.
  Software não separa com confiabilidade o que já veio somado pelo cabo analógico.

Leia o [roteamento completo](audio-routing.md) antes de alterar cabos/filtros.
O sucesso histórico do perfil de um cabo não valida automaticamente o segundo.

## Iniciar, operar e encerrar

Clique **Iniciar reunião** para solicitar abertura dos aplicativos configurados
e iniciar as verificações de câmera. Confira as mensagens: aplicativo solicitado,
janela aberta e reunião efetivamente ativa são etapas diferentes.

O app começa com automação **pausada**. Depois de conferir o Texto do Ano e a
calibração, use **Ativar**. O sensor compara a saída secundária JWL com o repouso:
repouso corresponde a Palco; mídia real aciona Mídias; ao terminar, volta a Palco.
Não há promessa de resposta instantânea: leitura, estabilização e transição têm prazo.

O guardião protege a janela JWL **somente enquanto a automação está ativa**.
Sensor e guardião têm funções distintas. Durante Zoom no Salão, mídia externa
ou retorno, eles respeitam a escolha do operador e aguardam a troca finalizar.

| Comando do painel | Uso |
| --- | --- |
| Texto do Ano / Palco / Mídia | Seleção manual da cena correspondente no OBS |
| Zoom → Salão | Exibir janela secundária Zoom no Salão; clicar novamente solicita retorno ao JWL |
| Ativar / Pausar | Controlar automação e proteção periódica do JWL |
| Emergência (Tela Preta) | Solicitar cena segura configurada e pausar automação; conferir a saída real |
| Forçar JWL Telão | Solicitar recuperação explícita do JWL e encerrar o modo Zoom local; conferir a confirmação |
| Câmera | Iniciar/parar a câmera nativa usada no WhatsApp |
| Mic Zoom | Alternar seu próprio microfone; não controla microfones dos participantes |
| WhatsApp | Silenciar/liberar somente o áudio recebido do WhatsApp nas caixas |
| Mídia Externa | Escolher uma janela permitida e retornar explicitamente ao JWL após a apresentação |
| Volumes | Abrir diretamente os ganhos por fonte na categoria Áudio |
| Ajustes | Reunião/janelas, OBS/vídeo, áudio, instalação/plugins e diagnóstico |

Volumes e Ajustes têm ícones próprios, mantendo seus nomes e a mesma posição.
Para VLC/navegador, consulte o [passo a passo de Mídia Externa](external-media.md).
Players minimizados são restaurados antes da captura; aguarde a confirmação no
retorno ao JWL. Títulos duplicados continuam bloqueados para evitar seleção
incorreta no OBS.

O rótulo de Emergência não garante imagem preta: o resultado depende da cena
segura configurada e da conexão OBS. Sem OBS conectado, confira e opere a saída
pelo OBS antes de prosseguir.

Para Zoom → Salão, habilite **Usar dois monitores** no Zoom antes de entrar na
reunião. A apresentação local não envia a imagem dos participantes de volta ao
Program. Ambas as janelas devem permanecer abertas. Aguarde confirmação do
JWL no retorno, mesmo com automação pausada.

Para volume, use **Volumes** no painel principal e **Aplicar volumes**. A ação salva
somente os ganhos editados. Comece em 0 dB e aumente em passos pequenos, ouvindo
no receptor. O limitador não corrige entrada já distorcida nem remove ruído.

Para terminar, clique **Encerrar reunião**. O app solicita fechamento normal;
confirme no Zoom quando necessário e confira se há aplicativos ainda abertos.
Não instale atualizações com reunião/automação em andamento.

## Foto, calibração e disposição

**Foto do Texto do Ano:** imagem persistida para a cena OBS, com ano e confirmação
humana. Deixe JWL visível, sem mídia ou Zoom por cima. Confira o arquivo salvo e
a aplicação da fonte. [Passos e limites](yeartext-and-obs.md).

**Calibração do sensor:** referência de repouso para detectar mídia. Faça com
somente o Texto do Ano exibido na saída do JWL. Atualizar a foto da cena não
substitui esse procedimento.

**Disposição de janelas:** salve a disposição pelos ajustes após posicionar app
e JWL principal. Monitores/DPI diferentes exigem nova conferência; preservar a
saída secundária do JWL é um requisito separado.

F1 apresenta os atalhos. Atalhos globais são opcionais; conflitos precisam ser
informados, sem desativar indiscriminadamente atalhos do Windows.

## Diagnóstico rápido

| Sintoma | Verificação e ação |
| --- | --- |
| Git recusa atualizar | Guardar trabalho local e verificar códigos de saída; [procedimento](test-python-update.md) |
| OBS desconectado | Conferir servidor WebSocket, host/porta/senha e mensagem do app; não presumir a causa pelo indicador |
| Captura mostra JWL do operador | Preparar fonte HWND; conferir plugin/reinício OBS e [diagnóstico](jwl-hwnd-capture.md) |
| OBS mostra Zoom ou espelhamento | Suspender uso da cena insegura e revisar fontes; não substituir HWND por captura do monitor |
| Fonte HWND informa waiting/invalid_target | Conferir JWL secundário, monitor e estado nativo; esses estados não confirmam captura |
| JWL não voltou após Zoom | Aguardar/observar a mensagem de retorno e solicitar Forçar JWL; registrar horário se não confirmar |
| Mídia sem áudio remoto | Conferir fontes, mute, monitoramento, endpoints e microfone de cada chamada |
| Som duplicado/eco | Revisar retornos no mix e na entrada física; silenciar o caminho que recaptura a própria chamada |
| Volume baixo | Ajustar ganho da fonte e ouvir no receptor; [passos](audio-routing.md) |
| Ruído só no OBS | Manter incidente aberto e comparar a rota/filtros com entrada direta; Audio Monitor não comprova correção |
| Mic Zoom lento ou sem ação | Conferir mensagem/tooltip e [roteiro do microfone](zoom-microphone-control.md) |
| Câmera ausente/travando no WhatsApp | Conferir sessão/bridge/diagnóstico e carga de CPU; [teste da câmera](test-virtual-camera.md) |

Para relatar, informe revisão (`git rev-parse HEAD`), horário, ação, mensagem
e resultado esperado/observado. Não envie senhas, links de reunião ou nomes de
participantes. A confirmação atual da captura não encerra todos os cenários de
reinício/monitor nem o problema de vários destaques no Zoom secundário.
