# Guia do operador — versão de desenvolvimento

Este guia descreve o que existe hoje. O tutorial ilustrado completo será produzido após estabilizar a interface, com imagens reais e passos numerados de instalação, configuração, uso, testes e solução de problemas. Foto anual, assistente OBS completo e instalador ainda estão no [roteiro](roadmap-after-hall-validation.md).

## Instalar e abrir

Use os comandos do [README](../README.md) para preparar o ambiente de desenvolvimento. Aplicativos externos: [OBS Studio](https://obsproject.com/), [Zoom](https://zoom.us/download) e [JW Library](https://www.jw.org/pt/ajuda-online/jw-library/).

Configurações do app ficam em `%APPDATA%\MeetingAssistant\settings.json`. Feche o app antes de copiar esse arquivo como backup; ele pode conter informações privadas, portanto não o publique.

## Configurar o ambiente

1. No Windows, use área de trabalho estendida. Confira qual monitor atende ao Salão em Ajustes.
2. No JWL, ative a reprodução na segunda tela e deixe o texto do ano visível.
3. No OBS, habilite o servidor WebSocket e use os mesmos dados em Ajustes.
4. Configure as cenas e fontes do ambiente: **Texto do Ano** com a foto, **Palco** com a câmera e **Mídias** com a captura adequada do JWL. Mapeie os nomes reais no app.
5. Habilite dois monitores no Zoom antes de entrar na reunião. As duas janelas precisam existir para Zoom → Salão.
6. Se o Meeting Assistant abrir o OBS, solicitará a câmera virtual pelos parâmetros de inicialização. Se o OBS já estiver aberto, inicie-a manualmente se necessário; selecione OBS Virtual Camera no Zoom. A confirmação automática do estado ainda está pendente.
7. Configure o áudio separadamente. O retorno dos participantes não deve compor o áudio enviado de volta ao Zoom; a solução integrada ainda está pendente.

## Operar

- **Iniciar reunião:** abre/reaproveita aplicativos e solicita entrada pelo link salvo. Confira que estão prontos.
- **Verificar:** confere conexão OBS, nomes de cenas e informações de monitores/JWL.
- **Ativar automação:** acompanha mídia; repouso com texto do ano corresponde a Palco.
- **Zoom → Salão:** mostra participantes no monitor local; clicar novamente deve restaurar JWL.
- **Fundo / Palco / Mídia:** seleção manual da cena.
- **Cena segura → Palco:** pausa a automação e solicita Palco.
- **Observar mídia / Calibrar Texto do Ano:** ferramentas técnicas atualmente na tela principal, com mudança para Ajustes planejada. Calibrar altera referências do detector e ativa a automação; não salva a foto de apresentação do OBS.

O preview atual é obtido do OBS. Para confirmar a troca física, olhe também para o monitor do Salão.

## Testar com duas telas

1. Repetir JWL → Zoom → JWL três vezes com automação pausada.
2. Repetir com automação ativa.
3. Reproduzir e parar uma mídia: verificar Mídias → Palco e permanência do texto do ano.
4. Fora de Zoom → Salão, pressionar Windows+D e conferir restauração do JWL.
5. Reiniciar apenas o Meeting Assistant e repetir a troca.
6. Verificar a imagem recebida por outro participante do Zoom: não deve receber seu próprio retorno.
7. Registrar falhas e o identificador de telemetria exibido no rodapé.

## Solução de problemas

| Sintoma | Conferência inicial |
| --- | --- |
| OBS desconectado | OBS aberto, servidor WebSocket habilitado, host/porta/senha iguais |
| Cena não encontrada | Nome e mapeamento em Ajustes; hoje a criação é manual |
| Câmera ausente no Zoom | Iniciar câmera virtual no OBS e selecionar OBS Virtual Camera no Zoom |
| Janela secundária Zoom ausente | Dois monitores habilitados antes da reunião; não fechar manualmente a janela secundária |
| JWL não retorna | Registrar sessão/horário e verificar monitor físico; não considerar só o preview como evidência |
| Texto do ano tratado como mídia | Deixar somente texto do ano no JWL e usar calibração conforme sua confirmação |
| Sem segunda tela | Configurações e desenvolvimento podem continuar; projeção e captura física não podem ser certificadas |
| Áudio duplicado/eco | Conferir captura de retorno Zoom e roteamento da mesa; evitar que retorno componha envio |
| JWL fecha ao abrir | Verificar se também ocorre fora do app e registrar erro do Windows; não atribuir automaticamente à troca de telas |

## Tutorial ilustrado final — conteúdo obrigatório

Capturas reais da instalação limpa e primeiro uso; seleção de monitor; fontes/cenas OBS; câmera virtual; áudio; criação/atualização da foto anual; operação dos botões; encerramento; matriz de testes; erros comuns; atualização, backup e recuperação. Cada figura terá legenda, ação e resultado esperado, sem credenciais ou nomes de participantes.

## Encerrar e atualizar

O encerramento assistido está planejado. Por enquanto, confirme o fim da reunião e encerre os aplicativos conforme a rotina do operador. Para atualizar o app, feche apenas ele e siga o README. Não modifique o núcleo protegido para acomodar outras funções.

## Configuração da câmera IP

A nova configuração em Ajustes, os nomes padrão das cenas e o início do OBS na bandeja estão descritos em [Câmera IP e OBS](obs-ip-camera.md). Implementação entregue; teste físico ainda pendente. Salvar os campos não acessa a câmera; aplicar a preparação pode iniciar a recepção no OBS.

