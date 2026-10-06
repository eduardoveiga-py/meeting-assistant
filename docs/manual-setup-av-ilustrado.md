# Manual Ilustrado — Preparação da Máquina (Áudio e Vídeo)

> Guia visual baseado em `docs/manual-setup-av.md` do Meeting Assistant.

## Como usar
Siga as fases na ordem. As telas podem ter pequenas diferenças conforme a versão do Windows, OBS ou Zoom.

## 1. Entenda o caminho do áudio

**Mesa do salão → OBS → cabo virtual → Zoom/WhatsApp**

O objetivo é enviar voz e mídias para a chamada sem criar um caminho de retorno que provoque eco ou microfonia.

## 2. Windows 11

### Controle exclusivo
**Painel de Controle → Som → Propriedades → Avançado**

Desmarque **“Permitir que os aplicativos assumam o controle exclusivo deste dispositivo”** nos dispositivos usados pelo fluxo.

### Comunicações
**Painel de Controle → Som → Comunicações → Não fazer nada**

Isso evita que o Windows reduza o volume das mídias durante uma chamada.

### Sons do sistema
Use o esquema **Sem sons** e desative o som de inicialização.

### Energia e tela
Configure tela e suspensão para **Nunca** durante o uso no salão. No monitor/telão, confirme escala em **100%**.

## 3. VB-CABLE

Instale o VB-CABLE como administrador e reinicie o computador.

**Página oficial:** https://vb-audio.com/Cable/

![Windows Sound — CABLE Output](https://obsproject.com/media/pages/kb/application-audio-capture-guide/bbd0aa09f7-1767490240/vb-soundproperties.png)

**Regra mental:** aplicativo que envia áudio → `CABLE Input`; aplicativo que captura → `CABLE Output`.

### Sample rate
Padronize os dispositivos usados no fluxo em **48.000 Hz**, preferencialmente estéreo, com 16 ou 24 bits.

## 4. OBS Studio

### Áudio global

![OBS Settings — Audio](https://obsproject.com/media/pages/kb/application-audio-capture-guide/125981d4b5-1767490077/aac-disabledesktop.png)

Use **48 kHz**. Quando as fontes forem adicionadas diretamente às cenas, mantenha o áudio global desativado para evitar duplicação.

### Captura de áudio

![OBS — CABLE Output](https://obsproject.com/media/pages/kb/application-audio-capture-guide/9aa5d732be-1767490058/vb-selectsourceobs.png)

Adicione as fontes de áudio individualmente.

### Monitoramento

Quando o projeto usar monitoramento para alimentar a chamada, selecione o cabo virtual apropriado em:

**Configurações → Áudio → Avançado → Dispositivo de monitoramento**

![OBS — Monitoring Device](https://jshingler.github.io/img/blog/obs-virtual-cables/obs-audio-monitoring-device.jpg)

> **Atenção:** o mixer de áudio do OBS mudou em versões recentes. Use a opção equivalente da sua versão, sem forçar a interface antiga.

### Câmera virtual

![OBS — Start Virtual Camera](https://obsproject.com/media/pages/kb/virtual-camera-guide/642d49ea2c-1767490166/obs-controls-startvcam.png)

Clique em **Start Virtual Camera**.

## 5. Zoom

### Vídeo
**Configurações → Vídeo → OBS Virtual Camera**

### Áudio

![Zoom — Audio](https://justinguitarcommunity.b-cdn.net/original/3X/d/1/d15d22d72fea6e84e5c60cea000636d1d48b212f.png)

- **Microfone:** `CABLE Output` do cabo que recebe o áudio do OBS.
- **Alto-falante:** saída física que leva o retorno para o salão.
- **Perfil:** `Original sound for musicians`, quando esse for o procedimento adotado.

O Zoom informa que o modo **Original sound for musicians** reduz/desativa o processamento de supressão de ruído, sendo indicado para preservar melhor música e áudio de alta fidelidade.

## 6. WhatsApp Desktop

Quando for necessário separar o WhatsApp do Zoom:

- **Microfone:** Cabo B.
- **Alto-falante:** saída física do salão.
- Alimente o Cabo B pelo fluxo de áudio separado do OBS.

## 7. Checklist final

- [ ] Comunicações = **Não fazer nada**
- [ ] Controle exclusivo desativado
- [ ] Sons do sistema desativados
- [ ] Suspensão/tela = **Nunca**
- [ ] Dispositivos do fluxo = **48 kHz**
- [ ] OBS = **48 kHz**
- [ ] Sem Desktop Audio duplicando fontes
- [ ] Fontes aparecem no mixer do OBS
- [ ] Câmera virtual iniciada
- [ ] Zoom recebe o CABLE correto
- [ ] Retorno do Zoom vai para a saída física correta
- [ ] Original Sound configurado conforme o procedimento
- [ ] Teste sem eco/microfonia/áudio robótico

## Referências

- OBS Project — Application Audio Capture Guide: https://obsproject.com/kb/application-audio-capture-guide
- OBS Project — Virtual Camera Guide: https://obsproject.com/kb/virtual-camera-guide
- VB-Audio — VB-CABLE: https://vb-audio.com/Cable/
- Zoom Support — Áudio profissional: https://support.zoom.com/hc/pb/article?id=zm_kb&sysparm_article=KB0059998
