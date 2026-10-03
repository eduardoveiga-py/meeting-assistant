# Câmera própria — protótipo de vídeo, 27/09/2026

## O que este lote entrega

- Plugin OBS separado: lê Program após composição/transições, converte para NV12
  1280×720 BT.709 limitado e fornece quadros por uma conexão local.
- Tela Ajustes → Câmera própria / ponte OBS: iniciar/parar ponte, prévia de diagnóstico,
  sequência de quadros, taxa observada e cópia de diagnóstico sem imagens/credenciais.
- Windows 10 x64 pode testar a ponte e a prévia. A câmera própria exige Windows 11 x64
  build 22000+; Windows ARM64 ainda não é alvo deste protótipo.
- Provedor Windows 11 adaptado do exemplo MIT da Microsoft, com CLSID próprio,
  câmera de sessão e controle explícito. Sem quadro recente, entrega preto.
- Build nativo no GitHub Actions e pacote de teste com scripts de instalar/remover.

**Compilar não comprova funcionamento no WhatsApp.** O runner de build é Windows Server,
não um teste físico de Windows 11/WhatsApp. Não há assinatura nem instalador final ainda.
O núcleo validado JWL/Zoom, as cenas e a câmera virtual OBS usada pelo Zoom não são alterados.
O áudio não passa por esta câmera; continua no módulo de áudio/VB-CABLE.

A primeira etapa usa named pipes com acesso local restrito ao usuário do OBS, SYSTEM e
(serviço de câmera, somente vídeo) LOCAL SERVICE. Essa escolha permite a comunicação com
Frame Server fora da sessão do operador, sem exigir que o OBS crie memória Global elevada.
Não há servidor de rede. Uma instância OBS por máquina; execute app/OBS no mesmo usuário.
A ACL e a ativação no Frame Server precisam ser verificadas no ensaio Windows 11.

## 1. Atualizar o app e obter binários

Feche o Meeting Assistant; no PowerShell na pasta do projeto:

```powershell
git pull --ff-only
.\scripts\setup-dev.ps1
```

No GitHub do projeto, abra **Actions → Video native prototype → execução verde do commit
instalado → Artifacts → meeting-assistant-video-prototype-x64**. Baixe e extraia em uma pasta.
Se a execução não estiver verde, não use um pacote antigo como se fosse deste commit.
O pacote contém DLL da ponte, EXE de controle, DLL do provedor, licenças, hashes e script.
`SHA256SUMS.json` detecta corrupção; não substitui assinatura/autenticidade da origem.

## 2. Instalar somente a ponte no Windows 10

Fora de uma reunião, feche OBS antes de instalar. No PowerShell **como administrador**,
entre na pasta extraída e execute:

```powershell
.\install-video-native.ps1 -Component Bridge
```

O script usa `C:\Program Files\obs-studio` por padrão; se necessário informe
`-ObsDirectory 'D:\SeuOBS'`. Ele não encerra aplicativos, preserva backup da DLL anterior
se existir e copia somente o plugin deste módulo. Build usa cabeçalhos OBS 31.0.3 x64;
compatibilidade com a versão instalada deve ser confirmada pelo carregamento do plugin.

Abra OBS e inicie o app normalmente:

```powershell
.\scripts\run-dev.ps1
```

## 3. Testar no Windows 10 — sem câmera própria

1. Ajustes → **Câmera própria / ponte OBS (experimental)**.
2. Deve aparecer aviso de Windows 11 e o botão da câmera própria desabilitado.
3. Clique **Verificar ponte OBS**: envio inicialmente desligado, sem vídeo recente.
4. Clique **Iniciar envio de vídeo**. A prévia deve aparecer, contador avançar e taxa
   aproximar-se de 30/s se o OBS estiver produzindo 30 fps ou mais.
   A prévia atualiza só duas vezes por segundo para diagnóstico; não é o vídeo enviado à câmera.
5. No OBS, troque cenas e reproduza um vídeo com movimento. Confira que a prévia corresponde
   ao **Program**. Se usar modo estúdio, mudar só Preview não deve mudar esta saída.
6. Confira orientação, proporção e cores. Este protótipo tem saída fixa 16:9; valide usando
   um Program 16:9. Outros formatos precisam de tratamento de proporção antes da Release.
7. Clique **Parar envio de vídeo**: status desligado, imagem anterior removida. Reinicie e teste.
8. Feche OBS durante o teste: deve aparecer indisponível/sem quadro, sem travar o app.
   Reabra OBS e clique Iniciar novamente. O plugin sempre inicia com envio desligado.
9. **Copiar diagnóstico técnico** e cole a saída na conversa.
10. Fechar a tela encerra o teste, solicita parada da ponte e encerra a câmera própria se ativa.
    Não feche esta tela enquanto quiser continuar usando a câmera própria neste protótipo.

Se a ponte não carregar: OBS → Ajuda → Arquivos de log → Exibir log atual.
Procure `meeting-assistant-bridge` e envie erro, versão OBS e arquitetura. Não substitua
outros plugins. Se o envio não parar, reinicie OBS fora da reunião para encerrar a ponte.

## 4. Teste adicional no Windows 11 x64

Só após aprovar a ponte no computador de destino:

1. Na pasta do pacote, PowerShell como administrador:
   ` .\install-video-native.ps1 -Component Camera `.
2. Abra OBS e app; entre na tela experimental e inicie o envio.
3. Clique **Iniciar câmera própria**. Aguarde “Windows confirmou a câmera”. Isso confirma
   apenas a API; ainda não significa que WhatsApp a reconheceu.
4. Nas permissões de câmera do Windows, permita acesso aos aplicativos necessários.
5. Abra a seleção de câmera do WhatsApp e procure **Meeting Assistant** (o Windows pode
   acrescentar um sufixo de câmera virtual). Se não listar, reabra o WhatsApp uma vez.
6. Faça chamada de teste com outro dispositivo. Confirme imagem, cores, movimento e
   transições. Teste 10 minutos e registre consumo de CPU e eventual atraso.
7. Mantenha simultaneamente Zoom com **OBS Virtual Camera**. Confirme que os dois destinos
   funcionam e que Zoom → Salão continua sem enviar o retorno Zoom para o Program.
8. Pare somente o envio: câmera própria deve mostrar preto em vez do último quadro.
   Reinicie o envio e confira recuperação. Pare a câmera própria, reinicie-a e teste seleção.
9. Feche a tela experimental: câmera própria é encerrada, sem desligar câmera OBS/Zoom.

Se houver `CAMERA_ERROR 0x...`, copie o código. Se API iniciar mas câmera ficar preta,
registre se a prévia da ponte estava recente: isso separa captura OBS de ativação/IPC
no Frame Server. NDI permanece uma alternativa já disponível durante a validação.

## 5. Remover o protótipo

Pare a câmera, feche a tela experimental e os aplicativos que a usam. Para remover a
classe da câmera: ` .\install-video-native.ps1 -Component RemoveCamera ` (Windows 11).
Feche OBS e remova a ponte: ` .\install-video-native.ps1 -Component RemoveBridge `.
Scripts não removem cenas, fontes, câmera OBS ou configurações JWL/Zoom. Arquivos do
provedor são mantidos se ainda puderem estar carregados; limpeza final fica para o instalador.

## Retorno

```text
Commit instalado:
Windows (winver):
OBS versão / WhatsApp versão:
V1 — Plugin reconhecido / mensagem:
V2 — Prévia correta do Program:
V3 — Contador e taxa observada:
V4 — Parar / reiniciar / fechar OBS:
V5 — Diagnóstico copiado:
Windows 11 disponível? Sim / Não
V6 — API inicia / código de erro:
V7 — WhatsApp lista a câmera / imagem na chamada:
V8 — Zoom simultâneo e desempenho em 10 minutos:
```

## Build e limites de distribuição

Desenvolvedor: Visual Studio 2022 C++, Windows SDK recente, CMake, Git, Python e NuGet;
execute `scripts/build-video-native.ps1` no ambiente de desenvolvimento. O script baixa
fontes em commits fixos e restaura versões NuGet declaradas no exemplo. Use BuildRoot novo
para repetir, sem modificar fontes de terceiros fora da cópia de build.

O plugin usa API/cabeçalhos OBS GPL-2.0-or-later; deve ser distribuído com fonte e licença
correspondentes. O provedor adapta Microsoft Windows-Camera sob MIT e preserva seu aviso.
Fontes ficam fixadas em `fcd1910...` (OBS) e `626f8b1...` (Microsoft) no script de build.
Revisão de distribuição/licenças, assinatura, instalador integrado, preview independente,
múltiplas sessões, desempenho real e aprovação WhatsApp continuam pendentes.
