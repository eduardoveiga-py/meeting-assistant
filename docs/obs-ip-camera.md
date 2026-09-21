# Câmera IP no Palco e inicialização do OBS

Implementado em 21/09/2026. **Não validado com a câmera física.** O usuário pediu implementação sem teste no equipamento nesta etapa.

## Dados recuperados do contexto anterior

- Modelo: iM7-FC.
- IP inicial: 10.0.0.40.
- RTSP: porta 554.
- Serviço TCP: 37777; não utilizado na fonte OBS.
- Caminho sugerido no chat: `/cam/realmonitor?channel=1&subtype=0`.
- Não foram recuperados usuário/senha; permanecem vazios.

O acesso direto ao link do chat não disponibilizou seu conteúdo. Os dados acima foram recuperados pela busca de contexto pessoal. O caminho foi uma orientação anterior, não uma comprovação de recepção nesta implementação.

## Configurar quando for a hora

1. Abra Ajustes e preencha IP, usuário e senha. Porta padrão é 554.
2. **Salvar** somente guarda os campos localmente. Não faz chamada ao endereço da câmera.
3. Com OBS conectado, **Salvar e preparar cenas / câmera no OBS** pede confirmação e aplica a configuração. A fonte pode iniciar recepção RTSP; não use esse botão enquanto não quiser aplicar ao equipamento.
4. A conclusão confirma operações de configuração, não imagem recebida. Validar vídeo fica para depois.

Credenciais são codificadas corretamente na URL para aceitar caracteres especiais. Senha fica mascarada na interface, mas é armazenada nos dados locais do app e na configuração da fonte OBS. Não publicar esses arquivos nem logs do OBS, que podem conter a URL. O controlador não inclui a URL em suas mensagens de erro.

## Padrão das cenas

| Modo | Nome padrão |
| --- | --- |
| Fundo | Texto do Ano |
| Palco | Palco |
| Mídia | Mídias |

Não criar cena Zoom para esta função: Zoom → Salão continua sendo a saída local independente já validada.

A preparação cria cenas ausentes. Cenas anteriormente mapeadas são renomeadas quando o nome padrão não está ocupado; conflito impede a preparação antes das alterações. Depois do sucesso, o app salva os três nomes padrão e bloqueia sua edição na interface. Outras cenas não são apagadas.

Fonte própria: **Meeting Assistant - Câmera IP**, tipo fonte de mídia (`ffmpeg_source`), RTSP sobre TCP, enquadramento proporcional no canvas, áudio silenciado. Executar novamente atualiza a mesma fonte sem duplicá-la. Fontes antigas do Palco são preservadas e precisam ser revistas pelo operador; nenhuma é apagada/desativada automaticamente.

Se houver falha após renomear, tenta restaurar os nomes anteriores. O OBS não oferece uma transação completa: itens criados podem permanecer em falha parcial. A interface informa preparação incompleta e não declara sucesso. Conferir antes de repetir.

As cenas novas Texto do Ano e Mídias são estruturas; suas fontes ainda precisam ser configuradas. Este recurso não implementa captura anual nem configuração completa do JWL.

## OBS na bandeja e início automático

Ao abrir OBS por Iniciar reunião, o app usa:

```text
--minimize-to-tray --startvirtualcam
```

OBS já aberto é reaproveitado, sem reinício. Os argumentos são de inicialização; não garantem câmera virtual ativa em uma instância que já estava aberta.

Em Ajustes → Inicialização da reunião, a opção **Iniciar OBS ao entrar no Windows, na bandeja** cria um atalho por usuário com diretório de trabalho correto e os mesmos argumentos. Só é aplicada ao salvar a alteração; não abre OBS imediatamente. Desativar remove apenas o atalho criado pelo Meeting Assistant. Atalho de OBS já existente na pasta Inicializar gera aviso para evitar duplicação; entradas de outras ferramentas/agendador/Registro precisam ser conferidas separadamente.

Referência: [parâmetros oficiais do OBS](https://obsproject.com/kb/launch-parameters). O executável é localizado automaticamente nos caminhos usuais ou informado em Ajustes.

## Limites da entrega

- Sem instalação/alteração na câmera nem teste na rede do usuário.
- Nenhuma mudança nos arquivos protegidos de janelas, guardiões ou detector de mídia.
- Foto anual e áudio de microfones continuam etapas próprias.
- Verificação feita com cliente OBS simulado e testes de integridade. Conexão RTSP, imagem, permissões de inicialização e câmera virtual real aguardam validação no Windows do operador.

