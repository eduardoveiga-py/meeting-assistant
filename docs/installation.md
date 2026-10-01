# Instalação do Meeting Assistant

## Requisitos

- Windows 11 x64, build 22000 ou superior (requisito da versão atual em desenvolvimento).
- OBS Studio.
- Zoom para desktop.
- WhatsApp Desktop quando for usar o retorno do salão.
- JW Library para Windows.
- VB-CABLE quando for usar o áudio de mídia no Zoom ou no WhatsApp.

**Python não é necessário.** O instalador do Meeting Assistant inclui o runtime e as bibliotecas Python usadas pelo aplicativo.

## Execucao em Python durante o desenvolvimento

```powershell
git pull --ff-only
.\scripts\run.ps1
```

Requer Python 3.12 x64. O script prepara `.venv`, instala as dependencias do projeto
quando necessario e executa o codigo da pasta `src`. Nao abre o aplicativo
empacotado. `-Source` continua aceito por compatibilidade, mas Python ja e o padrao.

Se camera e ponte estiverem instaladas, o script as reutiliza. Caso faltem, baixa
`MeetingAssistant-Windows11-native.zip` da release `native-latest`, verifica os
hashes e solicita elevacao para instalar. Feche OBS e WhatsApp antes da instalacao.

Para atualizar as DLLs/host nativos:

```powershell
.\scripts\run.ps1 -Refresh
```

Para usar um pacote nativo que voce ja extraiu:

```powershell
.\scripts\run.ps1 -NativePackageDirectory 'C:\Camera Meeting Assistant'
```

Para iniciar agora com os componentes que ja estao instalados, sem download:

```powershell
.\scripts\run.ps1 -SkipNativeInstall
```

Essa opcao nao instala nem verifica os componentes nativos. Camera e preview
dependem de eles estarem instalados e do OBS estar aberto com a ponte carregada.

Se houver bloqueio de scripts:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

O downloader exige que a release nativa tenha sido publicada pelo workflow
**Windows 11 video**; alterar o workflow localmente nao publica arquivos.
Um repositorio privado pode usar GitHub CLI autenticado, ou uma URL acessivel
em `MEETING_ASSISTANT_NATIVE_URL`. Nenhum token deve ser colocado no codigo.

As instruções abaixo se aplicam ao instalador da release candidata 0.6.0-rc1.

## 1. Instalar o Meeting Assistant

Baixe `MeetingAssistant-Setup-<versão>.exe` na Release do GitHub e execute.

Feche app, OBS e WhatsApp. O instalador solicita permissão de administrador para
registrar a câmera e instalar a ponte OBS. Selecione a pasta do OBS e mantenha os
componentes câmera/ponte habilitados. Se ainda não tiver OBS, desmarque a ponte;
depois use o assistente para instalar OBS e instalar os componentes nativos.
Python, bibliotecas e Microsoft Visual C++ x64 estão incluídos.

## 2. Instalar os aplicativos externos

O Meeting Assistant não redistribui OBS, Zoom, JW Library ou VB-CABLE.

Na primeira abertura, use **Assistente de instalação e configuração** para verificar o ambiente. O assistente pode solicitar o WinGet para instalar OBS e Zoom. Para JW Library, use a Microsoft Store/site oficial. Para VB-CABLE, use o instalador do fabricante.

## 3. Configurar o OBS

1. Abra o OBS.
2. Habilite **WebSocket Server** e defina a mesma porta/senha usada no Meeting Assistant.
3. Confirme as cenas `Texto do Ano`, `Palco` e `Mídias`.
4. Em **Configurações → Áudio → Avançado**, defina o dispositivo de monitoramento como **CABLE Input**.
5. Não capture a mesma saída pelo `Desktop Audio` e pela captura de aplicativo.

## 4. Configurar Zoom e WhatsApp

1. Em **Configurações → Áudio** dos dois aplicativos, selecione **CABLE Output** como microfone quando quiser enviar a mistura monitorada pelo OBS.
2. Use os alto-falantes físicos do Salão como saída de ambos. O Meeting Assistant inicia o retorno do WhatsApp silenciado e oferece um botão separado para liberá-lo.
3. Se precisar de áudio estéreo, teste o modo de áudio original/estéreo do Zoom com outro dispositivo.
4. Use **OBS Virtual Camera** como câmera do Zoom e **Meeting Assistant** no WhatsApp.
5. Ao abrir o Meeting Assistant, a câmera nativa do Windows 11 é iniciada depois que o OBS conecta. Na tela principal, use **Parar câmera WhatsApp** ou **Tentar câmera WhatsApp** quando precisar controlá-la.

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
      Zoom + WhatsApp
```

Para as fontes da mesa e mídias enviadas aos dois aplicativos, use **Monitor Only** no OBS.

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

Para a câmera e prévia atualizadas, o pacote é obtido automaticamente pelo `run.ps1`.
O roteiro técnico e os testes manuais continuam em [pacote Windows 11 e câmera](test-virtual-camera.md).
