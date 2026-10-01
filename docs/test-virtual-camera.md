# Teste — câmera Windows 11 e prévia contínua (revisão 3)

Requer Windows 11 **x64**, build 22000 ou posterior, e OBS Studio x64 local.
O computador de testes do operador agora possui Windows 11 e dois monitores.
Não é necessário NDI, DirectShow Compat, driver UMDF experimental ou Python instalado.
A compatibilidade real com a versão instalada do WhatsApp ainda precisa ser confirmada.

## Instalar o pacote de desenvolvimento

1. Na execução mais recente do workflow **Windows 11 video**, baixe o artefato
   `meeting-assistant-video-windows11-x64` e extraia tudo numa **pasta nova**.
2. Feche Meeting Assistant, OBS e WhatsApp. Não misture arquivos dos ZIPs antigos.
3. Abra PowerShell **como administrador** na pasta extraída:

```powershell
Unblock-File -LiteralPath .\install-video-native.ps1
.\install-video-native.ps1 -Component All
```

O instalador verifica hashes, testa a ativação da fonte Microsoft adaptada, instala
nosso plugin no OBS e registra nossa fonte de câmera no Windows. Não modifica cenas,
fontes, áudio, Secure Boot ou assinatura de drivers. O requisito Windows 11 elimina
a necessidade do experimento de driver que estávamos preparando para Windows 10.
Se o OBS estiver em outro caminho, acrescente `-ObsDirectory 'D:\OBS Studio'`.
Se ainda existir **Meeting Assistant Compat** da tentativa anterior, com OBS/WhatsApp/
Zoom fechados, use `-Component RemoveLegacy` para remover apenas seu registro.
Não precisa desinstalar as câmeras de outros programas para testar esta versão.

4. Reabra o OBS. Abra `MeetingAssistant\MeetingAssistant.exe` dentro do ZIP extraído
   com o usuário normal. Este é o app atualizado; não use o atalho da versão antiga.
   Ele inclui Python e bibliotecas. As configurações existentes são reutilizadas.

## Teste 1 — prévia da tela principal

- Configure a saída do OBS para 30 fps e reproduza um vídeo com movimento.
- O preview deve acompanhar **Program**, inclusive as transições reais do OBS.
- Em modo estúdio, altere somente Preview: a imagem do app deve permanecer em Program.
- Redimensione o app e verifique se os controles continuam visíveis.
- Abra **Ajustes → Câmera para WhatsApp — Windows 11**. Confira ponte e prévia próximas
  de 30 fps, após cerca de 5 segundos. A medição da prévia conta quadros entregues
  ao renderizador Qt; não mede a tela remota nem certifica a taxa exibida pelo WhatsApp.

## Teste 2 — câmera e WhatsApp

- Clique **Iniciar câmera para WhatsApp**. Aguarde a confirmação do Windows.
- Abra/reabra o WhatsApp e selecione **Meeting Assistant Windows Virtual Camera**
  (o Windows acrescenta o sufixo ao nome).
- Faça uma chamada com outro dispositivo e confirme a imagem **recebida do outro lado**.
- Troque Palco → Mídias → Palco. Confira cores, proporção, fluidez e ausência de congelamento.
- Feche a tela de câmera e Ajustes para voltar à operação. A câmera continua ativa.
- Abra novamente os controles de câmera: a prévia deve continuar junto com o WhatsApp.
- Clique **Parar câmera**: o envio deve parar; a prévia local continua funcionando.
- Inicie novamente e repita a seleção no WhatsApp se ele não renovar a lista automaticamente.

O teste trata somente vídeo. O áudio segue a configuração existente, separadamente.
A confirmação `CAMERA_STARTED` significa registro/ativação pelo Windows; não significa
aprovação do WhatsApp. `camera_approved_in_whatsapp` permanece falso até validação humana.

## Teste 3 — retomada e dois monitores

- Com a câmera ativa, feche e reabra o OBS. A prévia deve se reconectar; a câmera deve
  voltar a receber vídeo quando o OBS estiver pronto. Durante a falta de quadros,
  a câmera fornece preto e a prévia informa indisponibilidade, sem manter imagem antiga.
- Com Zoom aberto em dois monitores, repita Zoom → Salão → JWL.
- Pressione Windows+D e confira a recuperação do JWL na segunda tela.
- Texto do ano deve continuar levando ao Palco; mídia ao Mídias, seguida de Palco ao terminar.
- Saia do Meeting Assistant: a câmera de sessão deve ser encerrada; OBS/JWL/Zoom continuam abertos.

## Diagnóstico para retornar

Copie **Copiar diagnóstico técnico** após 20 segundos com vídeo em movimento e a
câmera ativa. Informe:

- Teste 1: fluidez, `bridge_fps`, `preview_fps`.
- Teste 2: câmera apareceu? Vídeo chegou ao outro dispositivo? Qual versão do WhatsApp?
- Teste 3: retomada OBS e ciclo JWL/Zoom funcionaram?

Se a câmera não aparecer, mantenha-a ativa no app e rode, na pasta do pacote:

```powershell
.\meeting-assistant-camera-inventory.exe
```

Envie a saída inteira. Se `CAMERA_ERROR` aparecer, envie o código hexadecimal.
Para 0x80070005, confira **Configurações → Privacidade e segurança → Câmera**, incluindo
acesso de aplicativos e aplicativos da área de trabalho. Não altere proteções do sistema.

## Remover nossos componentes

Feche app, OBS e clientes da câmera. PowerShell administrador, pasta do pacote:

```powershell
.\install-video-native.ps1 -Component RemoveCamera
.\install-video-native.ps1 -Component RemoveBridge
```

A câmera é de sessão e some quando seu processo termina. O registro COM próprio é
removido pelo comando. Arquivos da câmera são mantidos caso algum cliente ainda
esteja usando a DLL; nenhum dispositivo de outros fabricantes é removido.
