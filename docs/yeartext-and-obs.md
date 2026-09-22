# Texto do Ano e fontes OBS — teste com o operador

Implementado em 21/09/2026; testes automatizados não substituem o teste físico com JWL, OBS e dois monitores.

## Atualizar a instalação de desenvolvimento

Feche somente o Meeting Assistant, mantendo JWL e Zoom abertos:

```powershell
cd C:\MeetingAssistant\meeting-assistant
git pull --ff-only
.\scripts\run-dev.ps1
```

Nenhuma biblioteca nova foi acrescentada nesta entrega.

## Capturar e salvar a foto

1. Deixe somente o Texto do Ano na janela secundária JWL. Pare a mídia e Zoom → Salão; aguarde a restauração.
2. Em **Ajustes**, abra **Texto do Ano, captura JWL e câmera virtual…**. A tela usa os ajustes já salvos: salve mudanças de monitor/OBS antes de abri-la.
3. Clique em **Criar foto — capturar JWL**, ou **Atualizar foto** quando já existir.
4. Confira a prévia, informe o ano que o texto realmente representa e marque a confirmação.
5. Clique em **Salvar foto e aplicar no OBS**.

A captura só aceita a janela JWL já identificada no monitor selecionado, visível, não minimizada/cloaked e sem outra janela cobrindo os pontos verificados. Posição e identidade são verificadas antes/depois da captura. A prévia e confirmação humana continuam necessárias para conteúdo, pequenas sobreposições e ano.

Arquivos ficam em `%APPDATA%\MeetingAssistant\yeartext`: cada PNG é imutável; `current.json` aponta para a foto vigente, com hash, ano e data. Falha ao salvar a nova imagem não substitui a anterior. Não distribuir essas imagens com o código.

Foto inexistente/corrompida ou ano diferente gera aviso não modal na abertura e a cada minuto, com acesso à ferramenta. O aviso não pausa a reunião nem apaga a foto. A foto não recalibra o sensor e não ativa automação.

## Aplicação ao OBS

O app cria/atualiza a fonte própria **Meeting Assistant - Texto do Ano**, tipo imagem, na cena mapeada a Fundo. Mantém outras fontes, posiciona a fonte própria acima delas e ajusta proporcionalmente ao canvas. Confira as margens e composição no OBS.

Se OBS estiver desconectado, a foto permanece salva e pendente. Na próxima conexão local, tenta aplicar e confirma o caminho da fonte. Também é possível clicar **Aplicar foto já salva no OBS**. Aplicação de arquivo/janela é suportada para OBS no mesmo computador (localhost/127.0.0.1/::1).

A confirmação significa configuração aplicada; observar o conteúdo continua sendo um teste do operador.

## Preparar a cena Mídias

1. Com o JWL secundário visível, clique **Preparar janela JWL em Mídias** e confirme.
2. O app cria/reutiliza **Meeting Assistant - JWL**, tipo captura de janela, vinculada à identidade JWL observada.
3. Exige uma opção exata e de título único na lista do OBS. Em ambiguidade ou ausência, informa a falha e não seleciona outra janela.
4. Usa captura de janela Windows Graphics Capture, correspondência de título exata, sem cursor e sem áudio. Ajusta proporcionalmente ao canvas e preserva fontes anteriores.
5. Confira no OBS o texto do ano e depois uma mídia. Não considerar só a mensagem de configuração como prova de vídeo.

Não usa captura de monitor como alternativa e não altera a cena Program. Fonte nova permanece desativada se a identificação falhar. Fontes existentes são preservadas; configurações OBS não são uma transação, portanto revise o resultado em caso de falha parcial.

## Câmera virtual

**Iniciar reunião** solicita a câmera virtual depois de verificar os aplicativos, mesmo com OBS já aberto. A ferramenta também oferece **Ligar e verificar câmera virtual**. Consulta estado, inicia somente se parada e exige confirmação ativa, com espera limitada para OBS desconectado/iniciando. Não usa alternância que desligaria uma câmera ativa.

Selecionar OBS Virtual Camera no Zoom continua sendo necessário. A câmera virtual não leva áudio; roteamento de áudio é outra etapa.

## Verificação final hoje

- Capturar, cancelar uma prévia e atualizar foto; conferir arquivo e fonte OBS.
- Usar **Verificar fontes e câmera virtual**: distinguir estrutura válida de conteúdo visual correto.
- Reproduzir/parar mídia, verificar Mídias → Palco.
- Alternar JWL ↔ Zoom, inclusive com automação pausada, e conferir o retorno JWL.
- No outro participante, verificar que Zoom → Salão não retorna o vídeo dos próprios participantes.
- A função de câmera IP não foi acionada como parte desses passos; teste dessa câmera permanece separado.

Em erro, informar mensagem exata e sessão do rodapé. Não modificar o núcleo protegido nem enfraquecer a identificação de janela para contornar uma falha.

