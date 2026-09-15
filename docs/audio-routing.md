# Arquitetura de áudio — JW Library, OBS e Zoom

## Objetivo

Enviar para o Zoom o áudio das mídias reproduzidas no JW Library sem depender de compartilhamento de tela/som do Zoom.

O vídeo continuará chegando ao Zoom pela câmera virtual do OBS. Como câmera virtual transporta vídeo, o áudio precisa entrar no Zoom por um dispositivo de entrada de áudio separado.

## Arquitetura recomendada

```text
JW Library ──> OBS (Application Audio Capture) ─┐
                                                ├─> Mix de monitoramento do OBS
Mesa/Microfone ──> OBS (Audio Input Capture) ──┘
                                                        │
                                                        v
                                              Dispositivo de áudio virtual
                                                        │
                                                        v
                                                Microfone do Zoom

Zoom (áudio remoto) ──> saída física / mesa / caixas
                         NÃO retornar ao mix enviado ao Zoom
```

## Princípios

1. O OBS é a fonte de verdade do áudio enviado ao Zoom.
2. O JW Library deve ser capturado como áudio de aplicativo quando possível.
3. O Zoom recebe um mix pronto como se fosse um microfone.
4. O áudio que chega do Zoom não pode voltar para o mesmo mix enviado ao Zoom, evitando eco/loop.
5. Nenhum fluxo essencial deve depender de cliques por imagem.

## Implementação prevista

- Capturar o JW Library por `Application Audio Capture` do OBS no Windows.
- Capturar a mesa/microfone como uma fonte independente no OBS.
- Configurar um dispositivo virtual de áudio como dispositivo de monitoramento do OBS.
- Marcar apenas as fontes destinadas ao Zoom como `Monitor and Output`.
- Configurar o endpoint de gravação correspondente do dispositivo virtual como microfone do Zoom.
- Roteamento do áudio remoto do Zoom deve permanecer fora desse retorno.

## Mix-minus

Se a mesa física devolve para o computador um sinal que já contém o áudio remoto do Zoom, é obrigatório usar um bus/auxiliar mix-minus na mesa ou uma separação de software. O sinal enviado de volta ao Zoom deve excluir o próprio retorno do Zoom.

## Configuração inicial do Zoom

O aplicativo terá um diagnóstico para verificar qual dispositivo de microfone está selecionado no fluxo previsto e mostrará instruções quando a configuração não puder ser alterada automaticamente com segurança.

Para mídias, `Original sound for musicians` pode ser útil porque reduz processamento agressivo de fala. A opção de cancelamento de eco e modos de alta fidelidade deve depender da topologia real da instalação; não será forçada sem teste de loop/eco.

## Dependência de dispositivo virtual

Não será embutido um driver de áudio de terceiros sem validar licença e instalação. O instalador do Meeting Assistant deverá detectar uma solução compatível e orientar/automatizar a preparação quando legal e tecnicamente adequado.
