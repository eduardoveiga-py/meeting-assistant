# Texto do Ano e fontes OBS — teste com o operador

Foto implementada em 21/09/2026; instruções de captura Mídias atualizadas em
07/10/2026 para a fonte por HWND. Foto persistida, referência do sensor e captura
ao vivo são funções distintas.

## Atualizar a instalação de desenvolvimento

Feche o Meeting Assistant. Na primeira instalação/atualização do componente
JWL, feche também OBS. Na pasta do projeto:

```powershell
cd C:\MeetingAssistant\meeting-assistant
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw "Atualização falhou; preserve as alterações locais." }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

O script baixa e instala a DLL pronta. Se o Git bloquear por alterações locais,
siga [test-python-update.md](test-python-update.md). Não é preciso compilar.

## Capturar e salvar a foto

1. Deixe somente o Texto do Ano na janela secundária JWL. Pare a mídia e Zoom → Salão; aguarde a restauração.
2. Em **Ajustes → OBS e vídeo → Texto do Ano**, confira monitor e conexão.
   Salve mudanças de monitor/OBS antes da captura.
3. Clique em **Criar foto do JWL**, ou **Atualizar foto do JWL** quando já existir.
4. Confira a prévia, informe o ano que o texto realmente representa e marque a confirmação.
5. Clique em **Salvar e aplicar foto**.

A captura só aceita a janela JWL já identificada no monitor selecionado, visível, não minimizada/cloaked e sem outra janela cobrindo os pontos verificados. Posição e identidade são verificadas antes/depois da captura. A prévia e confirmação humana continuam necessárias para conteúdo, pequenas sobreposições e ano.

Arquivos ficam em `%APPDATA%\MeetingAssistant\yeartext`: cada PNG é imutável; `current.json` aponta para a foto vigente, com hash, ano e data. Falha ao salvar a nova imagem não substitui a anterior. Não distribuir essas imagens com o código.

Foto inexistente/corrompida ou ano diferente gera aviso não modal na abertura e a cada minuto, com acesso à ferramenta. O aviso não pausa a reunião nem apaga a foto. A foto não recalibra o sensor e não ativa automação.

## Aplicação ao OBS

O app cria/atualiza a fonte própria **Meeting Assistant - Texto do Ano**, tipo imagem, na cena mapeada a Fundo. Mantém outras fontes, posiciona a fonte própria acima delas e ajusta proporcionalmente ao canvas. Confira as margens e composição no OBS.

Se OBS estiver desconectado, a foto permanece salva e pendente. Na próxima conexão
local, tenta aplicar e confirma o caminho da fonte. Também é possível clicar
**Aplicar foto salva no OBS**. Aplicação automática é suportada para OBS no mesmo
computador, inclusive por IP/nome que corresponda às interfaces locais; não apenas
localhost. OBS remoto exige acesso explícito ao arquivo, não ao caminho local do app.

A confirmação significa configuração aplicada; observar o conteúdo continua sendo um teste do operador.

## Preparar a cena Mídias

1. Abra OBS e JWL, habilite a segunda saída e selecione a Tela do Salão nos ajustes.
2. Em **Ajustes → OBS e vídeo → Fontes**, clique **Preparar captura JWL**. O app cria/reutiliza
   **Meeting Assistant - JWL (HWND)**, tipo `meeting_assistant_jwl_capture`.
3. O vínculo usa o HWND identificado pelo app; títulos duplicados/vazios não
   selecionam a janela do operador. Identidade e imagem nativa precisam ser confirmadas.
4. A captura usa o backend Windows Graphics Capture do OBS, área cliente, sem cursor
   e sem áudio. Ajusta proporcionalmente ao canvas e preserva fontes anteriores.
5. A antiga **Meeting Assistant - JWL** fica desativada somente na cena gerenciada
   após a nova fonte confirmar captura. Confira no OBS o Texto do Ano e depois uma mídia.

Não usa captura de monitor como alternativa e não altera a cena Program. Fonte nova permanece desativada se a identificação falhar. Fontes existentes são preservadas; configurações OBS não são uma transação, portanto revise o resultado em caso de falha parcial.

Requer Windows 11 x64, OBS 31.0.3+ e Direct3D 11. A nova captura foi confirmada
pelo operador em 07/10/2026, sem resultados individuais de toda a matriz de
regressão. [Instalação e diagnóstico](jwl-hwnd-capture.md).

## Câmera virtual

**Iniciar reunião** solicita a câmera virtual depois de verificar os aplicativos,
mesmo com OBS já aberto. **OBS e vídeo → Fontes** também oferece **Ligar câmera
virtual do OBS**. Consulta estado, inicia somente se parada e exige confirmação ativa,
com espera limitada para OBS desconectado/iniciando. Não usa alternância que
desligaria uma câmera ativa. A câmera nativa do WhatsApp fica na aba **WhatsApp**
da mesma categoria e continua acessível no painel principal.

Selecionar OBS Virtual Camera no Zoom continua sendo necessário. A câmera virtual não leva áudio; roteamento de áudio é outra etapa.

## Verificação final hoje

- Capturar, cancelar uma prévia e atualizar foto; conferir arquivo e fonte OBS.
- Usar **OBS e vídeo → Fontes → Verificar fontes e plugins**: distinguir estrutura válida
  de conteúdo visual correto; verificar separadamente a câmera virtual.
- Reproduzir/parar mídia, verificar Mídias → Palco.
- Alternar JWL ↔ Zoom, inclusive com automação pausada, e conferir o retorno JWL.
- No outro participante, verificar que Zoom → Salão não retorna o vídeo dos próprios participantes.
- A função de câmera IP não foi acionada como parte desses passos; teste dessa câmera permanece separado.

Em erro, informar mensagem exata e sessão do rodapé. Não modificar o núcleo protegido nem enfraquecer a identificação de janela para contornar uma falha.

