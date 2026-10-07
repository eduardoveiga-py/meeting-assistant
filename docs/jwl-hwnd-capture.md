# Captura da segunda janela JWL por HWND

Windows 11 x64 e OBS **31.0.3 ou posterior**. Desenvolvimento continua com Python 3.12
e `scripts/run.ps1`; não é preciso instalar Visual Studio nem compilar no computador do operador.

A nova DLL registra `meeting_assistant_jwl_capture`. A fonte
**Meeting Assistant - JWL (HWND)** usa diretamente a janela secundária identificada
pelo aplicativo, mesmo quando as duas janelas têm títulos iguais ou vazios.
O plugin reutiliza o backend GPU Windows Graphics Capture (`libobs-winrt.dll`) do OBS.
Esse backend chama `IGraphicsCaptureItemInterop::CreateForWindow(HWND)`.
Nenhuma imagem é enviada pelo Python, nenhum monitor é capturado e nenhum aplicativo
de terceiros é usado. O plugin não modifica áudio, câmera virtual, janelas ou guardião.

## Atualizar e executar

1. Feche Meeting Assistant e OBS na primeira instalação deste componente.
2. Na pasta do projeto, execute `git pull --ff-only`.
3. Execute `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1`.
   O script verifica e baixa a DLL pronta, valida o SHA-256 fixado no código e pede
   elevação do Windows somente para copiar o plugin para a instalação do OBS.
4. Abra OBS e JWL, habilite a segunda tela no JWL, escolha a Tela do Salão nos ajustes.
5. No app, **Ajustes → Texto do Ano e fontes do OBS → Preparar janela JWL em Mídias**.
   Confirme a imagem no OBS antes de ativar a automação.

OBS instalado em outra pasta: acrescente `-ObsDirectory 'D:\OBS Studio'` ao comando.
`-SkipNativeInstall` pula explicitamente todas as instalações nativas; não prepara uma DLL ausente.

## Proteções e migração

O vínculo inclui HWND, PID, instante de criação dos processos, classe, relação entre
janela UWP e processo JWLibrary.exe, monitor físico e sessão do app. A fonte retorna
sem imagem quando esse vínculo é inválido. Ela nunca procura outra janela pelo título.
O app redescobre e atualiza o vínculo após reiniciar JWL/OBS. Guardião continua ativo
somente com automação ligada; captura não muda posição nem prioridade das janelas.

A antiga fonte **Meeting Assistant - JWL** é preservada e desativada somente na cena
Mídias depois que a nova fonte confirma captura. Capturas de monitor continuam bloqueadas.
O modo de simulação não libera captura insegura. A nova fonte não tem áudio: o áudio
das mídias permanece no barramento já configurado, evitando duplicação.

## Teste físico e diagnóstico

- Títulos iguais: OBS deve mostrar a saída do salão, não a interface do operador.
- Texto do Ano, vídeo, imagem e pausa: confirme enquadramento e fluidez.
- Automação ligada: mídia → Mídias; fim → Palco; Windows+D deve manter a recuperação.
- Três ciclos JWL → Zoom → JWL, com automação pausada e ativa: confira troca local,
  ausência de captura do Zoom no OBS e nenhum espelhamento na chamada.
- Feche e reabra somente JWL; depois somente OBS. Prepare novamente se o JWL não
  reabrir sua segunda janela. O HWND antigo não deve capturar outra janela.
- Use **Verificar fontes e câmera virtual**. O relatório inclui estado nativo,
  HWND confirmado e dimensões; a telemetria registra `jwl_capture_status`.

Estados `waiting`, `invalid_target`, `capture_failed` e `unbound` não são sucesso.
Se o plugin não aparecer, confira versão do OBS, reinício após instalar e o log do OBS.
Verifique **Ajuda → Arquivos de log → Ver arquivo de log atual**, procurando
`meeting-assistant-jwl-capture`. Não substitua a fonte por captura de monitor.

## Código reutilizado e validação

- [OBS Windows Graphics Capture](https://github.com/obsproject/obs-studio/tree/31.0.3/libobs-winrt), GPL-2.0-or-later.
- [API Microsoft CreateForWindow](https://learn.microsoft.com/windows/win32/api/windows.graphics.capture.interop/nf-windows-graphics-capture-interop-igraphicscaptureiteminterop-createforwindow).
- Backend fornecido pela instalação do OBS; compilação usa headers do commit
  `fcd1910bf5116b69404a6ecdda6efedd1d00ebdf`.

CI compila Windows x64, testa identidade/troca de processo e integridade do pacote.
Isso não substitui o teste físico em JWL com dois monitores. O contrato histórico
de troca JWL/Zoom e seus arquivos protegidos permanecem preservados.
