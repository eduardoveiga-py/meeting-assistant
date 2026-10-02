# Câmera de compatibilidade — Windows 10/11 x64

Protótipo separado DirectShow, baseado nos componentes de saída de libdshowcapture
(LGPL-2.1-or-later), commit ef8c1d2e19c93e664100dd41e1a0df4f8ad45430.
Código do módulo Meeting Assistant sob GPL-2.0-or-later; pacote inclui fontes para recompilar.
A câmera moderna Windows 11 e o núcleo JWL/Zoom permanecem preservados.

## Alcance e limites

- Windows 10 2004+ / Windows 11, ambos x64. Aplicativos consumidores x64.
- Nome: **Meeting Assistant Compat**, identidade COM exclusiva.
- Saída fixa 1280x720, 30 fps, NV12/I420/YUY2. Não transmite áudio.
- A ponte OBS existente fornece os quadros; o processo Python só autoriza o envio.
- Fonte sem envio autorizado ou quadro recente: preto. O registro da câmera persiste
  após fechar o app; isso é diferente da câmera moderna de sessão.
- Apenas um consumidor de câmera por vez. Enquanto uma câmera está ativa, a prévia
  interna pausa para não disputar a conexão. Não abrir Compat e Moderna simultaneamente.
- A integração é experimental: DirectShow não garante reconhecimento no WhatsApp.
  O teste decisivo é aparecer na lista e entregar vídeo ao outro participante.
- Ainda não há suporte x86/ARM64 nem teste físico no Windows 11 neste lote.

## Instalação

1. Atualize o app com `git pull --ff-only`.
2. Baixe o artifact da execução verde **Video native prototype** que inclua Compat,
   extraia numa pasta nova (sem misturar versões). Mantenha SHA256SUMS.json junto.
3. Feche Meeting Assistant, OBS, WhatsApp e Zoom. PowerShell x64 como administrador,
   na pasta extraída:

```powershell
Unblock-File -LiteralPath .\install-video-native.ps1
.\install-video-native.ps1 -Component Compat -VerifyOnly
.\install-video-native.ps1 -Component Compat
```

A ponte já instalada pode ser mantida se estiver funcionando a 30 fps. Para instalar
em computador novo, instale também `-Component Bridge` com OBS fechado.

O instalador verifica hashes, registra apenas o CLSID do Compat e executa o verificador.
Sucesso do verificador confirma criação COM e capacidades; não confirma recepção no WhatsApp.
Não é necessário instalar `-Component Camera` no Windows 10.

## Teste

1. Abra OBS e deixe o Texto do Ano ou um vídeo no Program.
2. Abra app → Ajustes → Câmera própria / ponte OBS.
3. Selecione **Compatibilidade — Windows 10/11** e clique **Iniciar câmera selecionada**.
   Automático escolhe Compat no Windows 10 e Moderno no Windows 11; pode escolher manualmente.
4. Abra WhatsApp e selecione **Meeting Assistant Compat** como câmera.
5. Confira a prévia do WhatsApp. Em chamada de teste, peça confirmação de movimento,
   cores, proporções e fluidez no outro dispositivo. A imagem não vem da prévia lenta do app.
6. Troque cenas no OBS. Pare o envio: o receptor deve mostrar preto, sem imagem antiga.
   Reinicie e confira retorno. Fechar a tela experimental também encerra o envio.
7. Copie o diagnóstico do app e informe se a câmera aparece e se o outro lado recebe vídeo.

Não use como fonte dentro do mesmo OBS que gera o Program: isso criaria realimentação visual.
Se não aparecer no WhatsApp, feche-o completamente e abra novamente uma vez. Não reinstale
outros drivers. Informe versão/arquitetura do WhatsApp e saída do verificador:

```powershell
& "$env:ProgramFiles\MeetingAssistant\CompatCamera\meeting-assistant-compat-check.exe"
```

## Remover

Com app/OBS/WhatsApp/Zoom fechados, execute o instalador como administrador:

```powershell
.\install-video-native.ps1 -Component RemoveCompat
```

Remove apenas o registro do Compat; mantém arquivos que algum cliente ainda possa ter carregado.
A câmera OBS e a câmera moderna têm identidades diferentes e não são removidas.
