# Guia rápido do operador — 0.5.1

Use o instalador publicado conforme [Instalação](installation.md). A versão 0.5.1 está preparada no código; confira a versão disponível em Releases antes de baixar.

Antes da reunião: confira tela estendida, JWL, OBS, Zoom e a saída recebida. Para atualizar ou resolver falhas, consulte [recuperação, matriz e retorno de versão](recovery-and-updates.md).

As configurações ficam em `%APPDATA%\MeetingAssistant`. Faça backup com o app fechado; essa pasta pode conter dados privados.

## Configurar o ambiente

1. No Windows, use área de trabalho estendida. Confira qual monitor atende ao Salão em Ajustes.
2. No JWL, ative a reprodução na segunda tela e deixe o texto do ano visível.
3. No OBS, habilite o servidor WebSocket e use os mesmos dados em Ajustes.
4. Configure as cenas e fontes do ambiente: **Texto do Ano** com a foto, **Palco** com a câmera e **Mídias** com a captura adequada do JWL. Mapeie os nomes reais no app.
5. Habilite dois monitores no Zoom antes de entrar na reunião. As duas janelas precisam existir para Zoom → Salão.
6. Iniciar reunião solicita e verifica a câmera virtual, inclusive com OBS aberto. Também há botão para isso na tela de Texto do Ano/fontes OBS. Selecione OBS Virtual Camera no Zoom; ativação no OBS não prova seleção no Zoom.
7. Use o assistente de áudio e confira o roteamento. O retorno dos participantes não deve compor o áudio enviado de volta ao Zoom. Áudio e câmera IP foram confirmados pelo responsável no equipamento atual em 24/09/2026.

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
| Cena não encontrada | Nome e mapeamento em Ajustes; o assistente pode criar cenas padrão, preservando as existentes |
| Câmera ausente no Zoom | Iniciar câmera virtual no OBS e selecionar OBS Virtual Camera no Zoom |
| Janela secundária Zoom ausente | Dois monitores habilitados antes da reunião; não fechar manualmente a janela secundária |
| JWL não retorna | Registrar sessão/horário e verificar monitor físico; não considerar só o preview como evidência |
| Texto do ano tratado como mídia | Deixar somente texto do ano no JWL e usar calibração conforme sua confirmação |
| Sem segunda tela | Configurações e desenvolvimento podem continuar; projeção e captura física não podem ser certificadas |
| Áudio duplicado/eco | Conferir captura de retorno Zoom e roteamento da mesa; evitar que retorno componha envio |
| JWL fecha ao abrir | Verificar se também ocorre fora do app e registrar erro do Windows; não atribuir automaticamente à troca de telas |

## Entender a pré-verificação

No assistente de instalação e configuração, aba **Preparar**, use **Verificar ambiente novamente**. O botão **Verificar / F9** da tela principal continua sendo o diagnóstico rápido existente.

- **INSTALAÇÃO:** aplicativo detectado no computador; não significa que está aberto.
- **CONEXÃO:** resposta ao teste naquele momento; câmera virtual ativa não prova seleção no Zoom.
- **CONFIGURAÇÃO:** cena existe, link foi preenchido ou foto foi salva; não certifica o conteúdo transmitido.
- **NÃO VERIFICADO:** a consulta não obteve evidência. Corrija a conexão e execute novamente.
- **OPERADOR:** marque apenas após observar o equipamento real. As caixas começam desmarcadas a cada abertura e não alteram a automação. Desmarque e repita o teste após mudar dispositivos ou roteamento.

## Encerrar e atualizar

O encerramento assistido está planejado. Por enquanto, confirme o fim da reunião e encerre os aplicativos conforme a rotina do operador. Para atualizar o app, siga o procedimento de [backup, atualização e retorno](recovery-and-updates.md). Não modifique o núcleo protegido para acomodar outras funções.

## Configuração da câmera IP

A nova configuração em Ajustes, os nomes padrão das cenas e o início do OBS na bandeja estão descritos em [Câmera IP e OBS](obs-ip-camera.md). Funcionamento no equipamento atual confirmado pelo responsável em 24/09/2026. Salvar os campos não acessa a câmera; aplicar a preparação pode iniciar a recepção no OBS.


## Foto do Texto do Ano e fontes

Siga o [passo a passo de captura e teste](yeartext-and-obs.md). A imagem só é salva após confirmação do operador. A gravação não altera a calibração do sensor. A verificação de fontes informa configuração, não valida sozinha o conteúdo mostrado aos participantes.


