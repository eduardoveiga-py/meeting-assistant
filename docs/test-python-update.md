# Atualizar e testar pelo Python

Fluxo atual: **Git → scripts/run.ps1 → Python 3.12 x64**. O script obtém
componentes nativos prontos; o operador não precisa de MSBuild nem de compilação.
Atualização de executável/instalador é uma entrega separada.

## Atualização habitual

Fora da reunião, feche o app. Para a primeira instalação do plugin JWL, feche
também OBS. Se for substituir componentes da câmera, feche WhatsApp e demais
clientes que estejam usando a câmera.

```powershell
cd C:\MeetingAssistant\meeting-assistant
git switch main
if ($LASTEXITCODE -ne 0) { throw "Falha ao selecionar main; atualização interrompida." }
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw "Falha ao atualizar; o app não será iniciado." }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

O terminal deve indicar a pasta correta em `Executando codigo Python de ...`.
A opção de política vale para o processo iniciado, sem mudança global do Windows.
Na primeira instalação de uma DLL, aceite a elevação para a cópia no diretório OBS.

## Se o Git informar que sobrescreveria alterações locais

Esse erro preserva seu trabalho e **não atualiza o código**. Guarde alterações
rastreadas/não rastreadas, mantenha o backup e só execute após sucesso:

```powershell
git stash push --include-untracked -m "backup-local-antes-atualizacao"
if ($LASTEXITCODE -ne 0) { throw "Falha ao guardar alterações; atualização interrompida." }
git stash list -1
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw "Falha ao atualizar; o app não será iniciado." }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

O stash não inclui arquivos ignorados; configurações/venv permanecem fora
desse backup. Atualizar o código não deve apagar `%APPDATA%\MeetingAssistant`.
Anote a entrada exibida por `git stash list`; novos stashes mudam seus índices.
Não reaplique automaticamente mudanças de guardião, sensor ou segurança de
captura. Compare-as com a revisão atual antes de integrar e mantenha o backup.
Não use descarte de arquivos para obter uma atualização aparentemente limpa.

Esse procedimento resolveu o bloqueio relatado em 07/10/2026.
[Registro INC-031](incident-history.md#inc-031--atualização-git-bloqueada-por-alterações-locais).

## Python e componentes nativos

- O script exige Python **3.12 estável x64**. Uma venv de outra versão é preservada
  em `.venv-backup-*` antes da recriação. Sem `py -3.12` disponível, ele para
  antes de mover o ambiente antigo.
- Dependências são atualizadas quando o manifesto muda. `-UpdateDependencies`
  solicita reinstalação explícita, sem significar atualização das DLLs.
- Câmera/ponte instaladas são reutilizadas. Mudança C++ exige binário correspondente,
  publicado pelo workflow Windows 11 video; `git pull` sozinho não o compila.
- O plugin JWL usa pacote separado, hashes fixados e instalação automática.
  Requer OBS **31.0.3+**, renderizador **Direct3D 11** e Windows 11 x64.
- Para OBS em outra pasta, acrescente `-ObsDirectory 'D:\OBS Studio'`.
  O script também consulta o caminho OBS salvo nos ajustes.
- `-SkipNativeInstall` pula explicitamente a instalação de todos os componentes
  nativos. Não use essa opção para tentar disponibilizar um plugin ausente.
- `-Refresh` solicita atualização de câmera/ponte. Use apenas quando essa
  atualização for necessária, fora da reunião e com os consumidores encerrados.

ZIP de código é uma alternativa somente quando corresponder à revisão desejada;
não substitua dados pessoais nem copie um pacote nativo de outra revisão.

## Conferência após atualização

1. Abra OBS/JWL e espere a conexão. Confira cenas e **Texto do Ano** no painel.
2. Na primeira preparação HWND, use **Ajustes → Texto do Ano e fontes do OBS →
   Preparar janela JWL em Mídias**. Confira saída do Salão na fonte
   **Meeting Assistant - JWL (HWND)**, não a janela do operador.
3. Confira câmera WhatsApp, imagem local e uma chamada de ensaio. A ponte precisa
   estar carregada no OBS; registro da câmera não substitui transporte de vídeo.
4. Teste início/fim de mídia, retorno ao Palco e troca JWL/Zoom/JWL.
5. Confira áudio remoto e o retorno WhatsApp inicialmente silenciado.
6. Para esta captura, siga também o [roteiro com dois monitores](jwl-hwnd-capture.md).

Para diagnóstico, registre `git rev-parse HEAD`, mensagem completa do terminal,
pasta executada, estado mostrado pelo app e horário. Não envie senhas, links
privados ou dumps integrais dos ajustes.
