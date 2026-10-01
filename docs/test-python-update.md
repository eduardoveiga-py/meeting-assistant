# Testar a atualizacao Python

1. Feche somente o Meeting Assistant.
2. Copie o conteudo da pasta `meeting-assistant` do ZIP sobre a pasta atual do
   projeto. Preserve `.venv`, os dados em `%APPDATA%\MeetingAssistant` e as DLLs
   que ja foram instaladas. O ZIP nao contem configuracoes pessoais.
3. Abra PowerShell x64 na raiz do projeto e execute:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

O terminal deve informar `Executando codigo Python de ...` com a pasta correta.
As dependencias Python sao atualizadas na primeira execucao desta correcao.
O script verifica Python 3.12 estavel x64. Se a `.venv` usar outra versao, precisa
encontrar 3.12 em `py -3.12`; entao preserva o ambiente anterior em `.venv-backup-*`
e cria a nova `.venv`. Se 3.12 nao estiver instalado, para antes de mover a antiga.
Se camera/ponte ja estiverem instaladas, o script as reutiliza.

Se nao quiser verificar ou baixar componentes nativos neste primeiro ensaio:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1 -SkipNativeInstall
```

4. Abra OBS. Aguarde a conexao do app. Confira `Texto do Ano` em vez de `Fundo`,
   o botao da camera WhatsApp e o controle do retorno de audio WhatsApp.
5. A camera deve tentar iniciar depois que o OBS conectar. Confira a imagem e
   o preview. OBS precisa ter carregado a ponte nativa; camera virtual instalada
   nao substitui a ponte.
6. Ensaie o ciclo de midia/Palco e Zoom/Salão/JWL ja validado.
7. Confira o retorno WhatsApp inicialmente silenciado e teste o botao para liberar
   e silenciar, usando uma chamada de ensaio.

Se precisar atualizar os componentes C++, feche OBS, WhatsApp e o app e use
`run.ps1 -Refresh`. O script precisa do pacote nativo publicado em `native-latest`.
Essa publicacao e feita pelo workflow Windows 11 video, nao por um git pull local.
Tambem pode usar `-NativePackageDirectory` com um pacote nativo completo ja extraido.

Para retornar um problema, envie a mensagem completa do PowerShell, o caminho
mostrado no inicio e o diagnostico do app. Nao envie senhas do WebSocket/camera.
