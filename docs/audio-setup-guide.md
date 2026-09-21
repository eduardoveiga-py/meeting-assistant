# Guia de Configuração de Áudio para Operadores (Zoom + OBS)

Com base na arquitetura do Meeting Assistant (`audio-routing.md`), o áudio do JW Library não é capturado diretamente pelo Zoom. O vídeo é enviado como uma câmera virtual através do OBS. Portanto, o áudio também deve ser orquestrado pelo OBS e enviado ao Zoom.

Atualmente, na configuração do salão:
1. Um cabo P2 traz o som dos microfones (mesa de som) para o PC.
2. O cabo de saída (fone/linha) envia o áudio do PC (JWL, Zoom etc.) de volta para a mesa (caixas).

Como o Zoom está configurado para ouvir o dispositivo de captura da placa mãe (Entrada P2 / Linha In), ele capta *somente a voz dos irmãos*, mas ignora o que está sendo tocado no PC (o vídeo/áudio do JW Library).

Para corrigir isso, a arquitetura do projeto definiu que o OBS será o "mixer" de saída.

### A solução

Precisamos de um **Dispositivo de Áudio Virtual** instalado no PC (como o *VB-Audio Virtual Cable* ou semelhante compatível, que possa ser instalado legalmente no PC da congregação).

**Passo a passo no OBS Studio:**
1. Adicione a **Mesa de Som (Microfones)** como fonte *Audio Input Capture*.
2. Adicione o **JW Library** como fonte *Application Audio Capture*.
3. Vá nas configurações do OBS > Áudio > Avançado, e defina o **Dispositivo de Monitoramento (Monitoring Device)** como a *Entrada do Cabo Virtual* (Cable Input).
4. No Mixer de Áudio do OBS, clique na engrenagem e vá em *Propriedades de Áudio Avançadas*. Marque a mesa de som e o JW Library como **Monitor e Output (Monitor and Output)**.

**Passo a passo no Zoom:**
1. Nas configurações de Microfone do Zoom, selecione a **Saída do Cabo Virtual** (Cable Output).
2. Assim, o Zoom passará a receber uma mistura limpa: O microfone da mesa *junto com* o áudio que o JW Library estiver reproduzindo.

**Cuidado com Ecos (Mix-Minus):**
Como o PC envia som de volta para a mesa (saída física), você precisa garantir que a mesa de som não devolva esse mesmo áudio (que inclui o Zoom) de volta pelo cabo de gravação. Caso contrário, o Zoom ouvirá a si mesmo e formará um eco infinito. A porta de saída da mesa de som (que vai para a entrada do PC) precisa ter as vias isoladas ou a mesa deve ser configurada em um *Auxiliar/Bus* de Mix-Minus, excluindo o canal do PC.
