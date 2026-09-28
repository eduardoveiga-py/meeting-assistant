# Meeting Assistant Camera PoC — Frame Server

Prova isolada de câmera independente, baseada em Microsoft SimpleMediaSource.
Objetivo: uma imagem sintética animada reconhecida pelo Media Foundation e
WhatsApp no Windows 10 x64 2004+ (build 19041+), antes de conectar o OBS.
Não usa NDI, DirectShow Compat ou MFCreateVirtualCamera. Não captura câmera,
áudio, desktop ou dados da reunião. Não altera o app nem JWL/Zoom.

## Estado

Código adaptado para compilação reproduzível. O pacote gerado é **SEM assinatura
para distribuição** e **SEM teste físico confirmado**. Compilar não comprova
instalação, enumeração ou entrega de vídeo no WhatsApp. Não execute o INF como
se fosse um instalador pronto. A etapa de assinatura/ambiente de teste será
avaliada separadamente; estes scripts não mudam Secure Boot, modo de teste,
certificados confiáveis ou configuração de inicialização.

## Alterações limitadas

- Upstream fixado em `f17f4ea91d6c3eafd26d950d40f1df462e0e0844`.
- SDK/WDK NuGet 10.0.26100.2454, VS2022, x64, Release; UMDF 2.31 para Win10 2004+.
- Identidade própria: `root\MeetingAssistantFrameServerPoC`;
  CLSID `C5C7589B-FF9A-4E96-B156-68479F4C75CA`;
  nome `Meeting Assistant Camera PoC`.
- INF usa o método AddService/WUDFRd documentado para Windows 10 em vez de
  incluir WUDFRD.inf, disponível somente no Windows 11+.
- Mantém as categorias de captura/vídeo/câmera do exemplo e o gerador sintético.
- Serviço UMDF próprio; não substitui os drivers das câmeras existentes.

## Verificação sem instalar

PowerShell na pasta extraída:

```powershell
.\preflight.ps1
```

`secure_boot: null` significa consulta indisponível/sem permissão, não desativado.
Não há instalação automática. O relatório contém build, arquitetura e estado
observável da assinatura/Secure Boot, sem serial ou identificação do computador.

## Próxima validação em ambiente de desenvolvimento

Após preparar um ambiente e assinatura de teste apropriados:
1. Registrar apenas o dispositivo do hardware ID acima e instalar seu pacote.
2. Confirmar o nome no Gerenciador de Dispositivos e no inventário MF.
3. Abrir Câmera do Windows e confirmar padrão animado, não apenas enumeração.
4. Abrir WhatsApp e confirmar padrão em chamada com outro participante.
5. Fechar/reabrir aplicativos e verificar recuperação.
6. Remover o dispositivo e o pacote específico, confirmando sua ausência.
Somente depois integrar a ponte OBS. Não alterar configurações de segurança do
notebook usado nas reuniões para tentar contornar uma falha de instalação.

## Fontes

- https://github.com/microsoft/Windows-driver-samples/tree/main/general/SimpleMediaSource
- https://learn.microsoft.com/en-us/windows-hardware/drivers/wdf/adding-the-reflector
- https://learn.microsoft.com/en-us/windows-hardware/drivers/wdf/umdf-version-history
- https://learn.microsoft.com/en-us/windows-hardware/drivers/stream/frame-server-custom-media-source

O pacote preserva a licença do exemplo Microsoft. A versão de produção exige
validação e o caminho de assinatura/certificação aplicável; isso não é realizado
pelo workflow experimental.
