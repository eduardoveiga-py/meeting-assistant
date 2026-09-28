# NDI → WhatsApp — integração assistida

O teste real em Windows 10 / WhatsApp 2.2637.100.0 x64 mostrou a câmera Compat
somente no DirectShow. As câmeras NDI aparecem também no Media Foundation,
cuja lista coincide com a apresentada pelo WhatsApp neste computador.
Esta integração reutiliza NDI Tools + DistroAV instalados pelo operador.
Não redistribui componentes NDI nem instala drivers silenciosamente.

## Atualização e preparação

1. Feche o Meeting Assistant, execute `git pull --ff-only` na pasta do projeto
   e abra o app pelo comando habitual. Não é necessário reinstalar o pacote
   de câmera nativa para este módulo Python.
2. Abra OBS com as cenas existentes. Caso DistroAV já esteja configurado,
   preserve a transmissão existente.
3. Primeira vez: OBS → Ferramentas → DistroAV NDI Settings / NDI Output Settings.
   Habilite **Main Output** e dê o nome **Meeting Assistant** à transmissão.
   Não habilite a saída Preview para este fluxo. O Program acompanha as cenas
   efetivamente exibidas, inclusive se o OBS estiver em modo estúdio.
4. App → Ajustes → Câmera própria/ponte OBS → **NDI → WhatsApp (Windows 10/11)**.
   Pare a câmera própria antes de abrir NDI. A ponte experimental não é necessária.
5. Clique **Verificar NDI no OBS**. O nome da transmissão deve aparecer e o estado
   deve ser ATIVA ou PARADA. Use **Iniciar saída NDI** se necessário.
6. Clique **Abrir NDI Webcam Input**. Se a localização automática falhar, selecione
   o executável do Webcam Input instalado. O programa costuma ficar na bandeja.
7. No ícone do NDI junto ao relógio, escolha o próprio computador e a transmissão
   do OBS. No WhatsApp, escolha o **NDI Webcam Video** correspondente ao canal.
   A escolha da fonte/canal é manual; não há confirmação automática de imagem
   recebida pelo WhatsApp. Preserve o microfone atual (mesa/VB-CABLE).

A saída do DistroAV pode transportar também áudio do OBS. Este módulo não muda
roteamento/mutes do OBS nem o microfone do WhatsApp. A transmissão NDI pode ser
descoberta na rede local; não é uma saída restrita ao processo do WhatsApp.

## Testes e retorno

- Verificação: estado e nome da fonte corretos; caso falhe, copie **diagnóstico NDI**.
- Chamada: outro participante confirma imagem do Program e fluidez.
- Troca de cenas: Palco/Mídias/Texto do Ano acompanha o OBS no WhatsApp.
- Parar: **Parar saída NDI**, depois **Verificar** confirma PARADA. Confira o
  comportamento da câmera no WhatsApp (preto, último quadro ou indisponível
  depende do receptor; o app não promete limpar um quadro já recebido).
- Reiniciar: **Iniciar saída NDI**, verificar ATIVA e retorno da imagem na chamada.
- Fechar a tela: mantém o estado atual da saída. Encerramento do app não equivale
  a parar NDI; use o botão Parar explicitamente. OBS Virtual Camera/Zoom seguem
  independentes. Não altere o núcleo JWL/Zoom para resolver problemas deste fluxo.

Envie: diagnóstico NDI, câmera escolhida, resultado da chamada e do parar/reiniciar.

## Limites e diagnóstico

- A ausência de `NDI Main Output` **não prova** falta do plugin: o DistroAV só
  cria essa saída quando habilitado nas configurações. O app orienta o preparo
  manual; não edita arquivos de configuração do OBS enquanto ele está aberto.
- Conexão WebSocket independente com timeout; usa os ajustes já salvos no app.
- Só controla nome `NDI Main Output` e tipo `ndi_output`; não controla gravação,
  streaming, câmera virtual, Preview ou saídas dedicadas.
- Confere o estado após Start/Stop. Se a transição não terminou, pede nova consulta.
- Fechamento aguarda consulta em andamento para não destruir uma thread ativa.
- O módulo é testado com respostas simuladas; funcionamento físico depende do
  teste do operador com as versões instaladas do DistroAV e NDI Tools.

Referências consultadas em 28/09/2026:
- [DistroAV main-output.cpp](https://github.com/DistroAV/DistroAV/blob/master/src/main-output.cpp)
- [OBS WebSocket](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md#outputs-requests)
- [NDI Webcam Input](https://docs.ndi.video/all/using-ndi/ndi-tools/ndi-tools-for-windows/webcam-input)
