# Arquitetura de áudio — JW Library, OBS, Zoom e WhatsApp

## Objetivo

Enviar para o Zoom e para o WhatsApp o mesmo mix local — microfones da mesa
mais mídias do JW Library, VLC, Edge ou Chrome — sem depender de
compartilhamento de tela/som do Zoom.

O vídeo continuará chegando ao Zoom pela câmera virtual do OBS. Como câmera virtual transporta vídeo, o áudio precisa entrar no Zoom por um dispositivo de entrada de áudio separado.

## Arquitetura recomendada

```text
JW Library ──> OBS (Application Audio Capture) ─┐
                                                ├─> Mix de monitoramento do OBS
Mesa/Microfone ──> OBS (Audio Input Capture) ──┘
                                                        │
                                                        v
                                              CABLE Input (VB-CABLE)
                                                        │
                                                        v
                                      CABLE Output (microfone compartilhado)
                                               ┌────────┴────────┐
                                               v                 v
                                       Microfone do Zoom  Microfone do WhatsApp

Zoom (áudio remoto) ──> saída física / mesa / caixas
WhatsApp (áudio remoto) ──> mesma saída, silenciado por padrão no app
                             NÃO retornar ao mix enviado aos aplicativos
```

## Princípios

1. O OBS é a fonte de verdade do mix enviado aos dois aplicativos.
2. O JW Library deve ser capturado como áudio de aplicativo quando possível.
3. Zoom e WhatsApp recebem um único mix pronto como se fosse um microfone.
4. A entrada física da mesa não deve conter o retorno dos aplicativos.
5. O áudio remoto do Zoom e do WhatsApp sai somente para o salão.
6. Nenhum fluxo essencial deve depender de cliques por imagem.

## Implementação prevista

- Capturar o JW Library por `Application Audio Capture` do OBS no Windows.
- Capturar a mesa/microfone como uma fonte independente no OBS.
- Configurar um dispositivo virtual de áudio como dispositivo de monitoramento do OBS.
- Marcar apenas as fontes destinadas ao Zoom como `Monitor and Output`.
- Configurar o endpoint de gravação correspondente como microfone do Zoom e do WhatsApp.
- Manter os alto-falantes dos aplicativos na saída física que alimenta a mesa.
- Deixar o retorno do WhatsApp silenciado pelo Meeting Assistant até o operador liberá-lo.
- Desativar o `Desktop Audio` global do OBS para não recapturar Zoom/WhatsApp.

## Controle do retorno do WhatsApp

O botão **WhatsApp** na tela principal controla somente a sessão de reprodução do
WhatsApp no Windows. Ele não altera o microfone, o Zoom, o JW Library ou o volume
geral do notebook. O estado inicial é silenciado por segurança; o guardião reaplica
o mute quando o WhatsApp recria sua sessão de áudio durante uma chamada.

O controle usa sessões do Windows Core Audio, não um mute global. Se o WhatsApp não
estiver aberto ou ainda não tiver uma sessão, o app permanece em estado seguro e
aguarda a chamada.

## Mix-minus

Se a mesa física devolve para o computador um sinal que já contém o áudio remoto do Zoom, é obrigatório usar um bus/auxiliar mix-minus na mesa ou uma separação de software. O sinal enviado de volta ao Zoom deve excluir o próprio retorno do Zoom.

## Configuração inicial do Zoom e do WhatsApp

O aplicativo orienta a seleção manual de `CABLE Output` nos dois aplicativos.
O controle de áudio do Windows pode ser automatizado com segurança, mas a seleção
de microfone dentro de Zoom/WhatsApp não é forçada por cliques frágeis.

Para mídias, `Original sound for musicians` pode ser útil porque reduz processamento agressivo de fala. A opção de cancelamento de eco e modos de alta fidelidade deve depender da topologia real da instalação; não será forçada sem teste de loop/eco.

## Dependência de dispositivo virtual

O VB-CABLE é instalado separadamente pelo pacote oficial. O Meeting Assistant não
redistribui o driver sem validação de licença; ele detectará os endpoints e orientará
a configuração. Sem um endpoint virtual, o Windows não oferece uma entrada de
microfone para a qual um aplicativo comum possa escrever um mix de outros programas.
