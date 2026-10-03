# Vídeo Windows 11 — decisão de 30/09/2026

Pedido do operador: Windows 11 obrigatório; uso pessoal no PC de testes com dois
monitores; câmera independente do NDI; Program do OBS para WhatsApp; prévia fluida.

## Decisão

Usar **MFCreateVirtualCamera**, com fonte de mídia baseada no exemplo MIT da Microsoft
Windows-Camera, fixado em `626f8b19c5f367602f2e89c6b314573d3776c9df`.
Mantemos nossa identidade COM `5108191D-9AD8-44F5-B760-7A35D433A427` e câmera de sessão.
O Windows 11 oferece essa API em modo usuário. Para este objetivo, não é necessário
prosseguir com driver UMDF/AVStream nem um runtime de câmera de terceiros.
Removidos da árvore ativa: DirectShow Compat, integração NDI, PoC SimpleMediaSource/UMDF
para Windows 10, seus workflows e testes. O histórico Git conserva a pesquisa anterior.

## Limites entre módulos

| Módulo | Responsabilidade | Não faz |
|---|---|---|
| `obs_bridge.cpp` | Receber Program bruto, reduzir para NV12 1280×720 a até 30 fps | Trocar cenas, áudio, janelas |
| `Preview.v1` | Canal local de prévia, independente da autorização da câmera | Autorizar envio para clientes |
| `Program.v1` e `Control.v1` | Quadros da câmera e autorização explícita de envio | Capturas JPEG por WebSocket |
| `program_video.py` | Uma conexão persistente, último quadro, reconexão e métricas | Criar/parar câmera |
| `program_preview.py` | Exibir NV12 via QVideoWidget/QVideoSink | Converter cada quadro em JPEG/RGB/QPixmap |
| `camera_session.py` | Ciclo de vida do processo nativo, comandos de envio e retomada | Gerenciar JWL/Zoom |
| `camera_host.cpp` + fonte MF | Registrar câmera de sessão e entregar Program | Depender de Python para transportar o vídeo |
| `virtual_camera_dialog.py` | Controles e diagnóstico | Encerrar câmera ao fechar a tela |

A prévia principal e a de configurações compartilham um leitor; não há filas ilimitadas
nem um consumidor competindo com o WhatsApp. A GUI retira somente o quadro mais recente.
O plugin captura Program enquanto OBS está aberto; o envio à câmera nasce desautorizado
e só é ativado por comando do app. Parar a câmera não desliga a prévia.
As transições visuais da prévia vêm do Program real, sem animação artificial adicional.

Integração com MainWindow limitada ao widget de prévia. Em main.py, somente requisito
Windows 11 e desativação dos screenshots periódicos do controlador. Hashes do núcleo
congelado não são atualizados. Não há alteração de áudio, guardião ou troca JWL/Zoom.

## Verificação

Testes de protocolo, conexão persistente, consumidores simultâneos, interrupção de
câmera, rejeição de quadros antigos, reconexão, controles e núcleo congelado.
CI Windows compila plugin/provedor/host e testa ativação COM sem instalar câmera.
O pacote inclui app portátil com Python/bibliotecas e instalação explícita dos dois
componentes nativos. Ensaio físico de GPU/renderização e recepção WhatsApp é separado
conforme [roteiro](test-virtual-camera.md); resultados não são presumidos pelo CI.

## Fontes primárias

- https://learn.microsoft.com/en-us/windows/win32/api/mfvirtualcamera/nf-mfvirtualcamera-mfcreatevirtualcamera
- https://github.com/microsoft/Windows-Camera/tree/master/Samples/VirtualCamera
- https://doc.qt.io/qt-6/qvideowidget.html
- https://doc.qt.io/qt-6/qvideoframeformat.html
