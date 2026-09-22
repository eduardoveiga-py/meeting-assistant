# Instalação do Meeting Assistant

## Requisitos

- Windows 10 ou Windows 11, 64 bits.
- OBS Studio.
- Zoom para desktop.
- JW Library para Windows.
- VB-CABLE quando for usar o áudio de mídia no Zoom.

**Python não é necessário.** O instalador do Meeting Assistant inclui o runtime e as bibliotecas Python usadas pelo aplicativo.

## 1. Instalar o Meeting Assistant

Baixe `MeetingAssistant-Setup-<versão>.exe` na Release do GitHub e execute.

O instalador é por usuário e normalmente não exige uma senha de administrador. Aceite o local padrão e crie o atalho desejado.

## 2. Instalar os aplicativos externos

O Meeting Assistant não redistribui OBS, Zoom, JW Library ou VB-CABLE.

Na primeira abertura, use **Assistente de instalação e configuração** para verificar o ambiente. O assistente pode solicitar o WinGet para instalar OBS e Zoom. Para JW Library, use a Microsoft Store/site oficial. Para VB-CABLE, use o instalador do fabricante.

## 3. Configurar o OBS

1. Abra o OBS.
2. Habilite **WebSocket Server** e defina a mesma porta/senha usada no Meeting Assistant.
3. Confirme as cenas `Texto do Ano`, `Palco` e `Mídias`.
4. Em **Configurações → Áudio → Avançado**, defina o dispositivo de monitoramento como **CABLE Input**.
5. Não capture a mesma saída pelo `Desktop Audio` e pela captura de aplicativo.

## 4. Configurar o Zoom

1. Em **Configurações → Áudio**, selecione **CABLE Output** como microfone quando quiser enviar a mistura monitorada pelo OBS.
2. Use os alto-falantes físicos do Salão como saída do Zoom.
3. Se precisar de áudio estéreo, teste o modo de áudio original/estéreo do Zoom com outro dispositivo.
4. Use **OBS Virtual Camera** como câmera quando necessário.

## 5. Áudio de mídia

```text
JW Library / VLC / Chrome / Edge
            ↓
    Captura de áudio OBS
            ↓
      Mixer / monitoramento
            ↓
        CABLE Input
            ↓
       CABLE Output
            ↓
           Zoom
```

Para uma fonte somente para o Zoom, prefira **Monitor Only** no OBS.

Não selecione o retorno do Zoom como parte da mistura enviada ao Zoom. Se a mesa já inclui o retorno, use uma saída mix-minus.

## 6. Primeira execução

1. Abra **Ajustes**.
2. Salve host, porta e senha do OBS.
3. Mapeie as três cenas.
4. Escolha a tela do Salão.
5. Use **Verificar**.
6. Abra o assistente de áudio e atualize as listas.
7. Escolha a entrada física da mesa e as fontes de aplicativos.
8. Confira o roteamento antes de ativar.

## 7. Primeiro teste

Faça o ensaio sem público: voz, JW Library, VLC, Chrome/Edge, voz + mídia, eco, Mídias → Palco e Zoom → Salão → JWL.

**Não faça o primeiro teste durante uma reunião pública.**

## Solução de problemas

**Python não é encontrado:** não instale Python para corrigir o instalador; reinstale a Release do Meeting Assistant.

**OBS não conecta:** confira WebSocket, porta, senha e OBS aberto.

**CABLE Input/Output não existe:** instale VB-CABLE e reinicie o Windows se o fabricante solicitar.

**JWL sem medidor:** alguns aplicativos exigem método alternativo de captura/roteamento.

**Áudio mono:** confira canal estéreo e `Mono` no OBS; depois confira áudio estéreo/original do Zoom.

**Eco:** retire o retorno do Zoom da mistura e evite duplicar `Desktop Audio` e captura por aplicativo.
