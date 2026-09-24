# Operação assistida — 0.6.0 em avaliação

## Voltar à referência estável

Antes deste trabalho foi criado o branch `checkpoint/stable-v0.5.1-before-operator-improvements`,
apontando para `13937b1862efb1fd383893498f597fb28deb149c`, o mesmo commit da tag `v0.5.1`.
Esse checkpoint e o checkpoint anterior do núcleo do Salão não devem ser movidos.

[Instalador estável 0.5.1](https://github.com/eduardoveiga-py/meeting-assistant/releases/tag/v0.5.1).
Feche o app, preserve uma cópia privada de `%APPDATA%\MeetingAssistant` antes de avaliar a nova
versão e mantenha o instalador anterior. Para voltar, reinstale 0.5.1 e restaure essa cópia com
o app fechado. Mudanças de cenas e fontes no OBS exigem backup separado da coleção/perfil OBS.
O checkpoint de código não é um backup das configurações do computador.

## Alterações no operador

- **Texto do Ano** substitui o rótulo Fundo; os nomes internos e mapeamentos existentes são preservados.
- Abas e campos recebem contraste explícito no tema escuro.
- Fechar o assistente pelo X, Escape ou Continuar depois usa o mesmo caminho. Durante uma tarefa,
  o fechamento fica pendente e acontece quando ela termina, sem `wait()` na interface.
  O formulário de ajustes incorporado deixa de ser modal; fechar a janela não deve deixar uma
  modalidade oculta bloqueando a principal.
- Preview OBS independente do canal de comandos: JPEG 480×270, qualidade 55, limite de 20 FPS,
  apenas o quadro mais recente e redução de trabalho quando a janela está oculta/minimizada.
  Rede, OBS e equipamento podem limitar a taxa real. O aviso de atraso não representa a qualidade no Zoom.
- O botão de microfone consulta o controle acessível do Zoom: **Silenciar** quando aberto,
  **Ativar** quando mudo. Confirma a mudança após a ação. Estado incerto não é mostrado como mudo;
  clicar nesse estado apenas repete a consulta. Não usa Alt+A às cegas nem silencia participantes.
  Idiomas cobertos inicialmente: português e inglês. Se a versão do Zoom não expuser o controle,
  usar o botão do próprio Zoom; compatibilidade física ainda precisa de teste.
- Seleção manual de Texto do Ano/Palco/Mídia pausa a automação usando o sinal existente.
  Zoom → Salão mantém seu contrato anterior. Use Ativar automação para retomar.
- Atalhos globais opcionais Ctrl+Alt+F2/F3/F4/F5/F7; desativados por padrão, sem repetição
  e sem execução enquanto um diálogo modal está aberto. Conflitos são informados.

## Contingência

O botão pausa a automação, preserva o retorno JWL existente quando necessário e verifica a fonte
de câmera selecionada. Fluxo de rede em reprodução: Palco. Fonte ausente, desativada, fluxo parado,
erro, USB removido ou estado inconclusivo: Texto do Ano. A cena e sua confirmação são verificadas.
Se Texto do Ano não tiver fonte habilitada, o app informa o problema sem declarar recuperação.

Para USB/captura, a consulta combina dispositivo enumerado e dimensões de vídeo informadas pelo OBS.
Isso não detecta toda falha física (por exemplo, imagem congelada ou tampa na lente). Fontes de plugins
sem informação de saúde usam o fallback conservador. Nenhuma troca de cena certifica a TV física.
O áudio não é alterado por esse botão. Antes da reunião, conferir a fonte do Texto do Ano e sua imagem.

## Painel Operação / F9

- **Reunião:** mesma pré-verificação usada pelo assistente, resumo para passagem de operador,
  conferência remota da sessão, registro local e comparação de monitor, câmera selecionada e cenas.
  A comparação não detecta todas as alterações externas feitas no OBS/Zoom.
- Medidores das fontes de voz/mídia gerenciadas pelo app, obtidos de eventos OBS. Sem evento recente,
  mostram não verificado. Não medem a recepção remota nem certificam ausência de eco.
- **Resolver:** roteiros por sintoma, solicitação de contingência, câmera virtual e diagnóstico detalhado.
- **Câmera:** manter IP iM7-FC existente; criar outra fonte de rede por URL; criar USB/placa de captura
  com escolha do dispositivo enumerado pelo OBS; usar fonte já configurada (incluindo plugins disponíveis).
  Todas são vinculadas a Palco. Fontes pessoais não são apagadas. Confira sobreposições no OBS.
  Fontes de câmera criadas pelo app têm áudio silenciado; fontes existentes preservam seu áudio.
- **Encerrar / Suporte:** pausar automação, silenciar o próprio microfone Zoom, desligar câmera virtual
  com confirmação, consultar release estável, abrir downloads e importar/exportar preferências.
  O encerramento final da reunião continua no Zoom.
- Perfis exportam apenas cenas/preferências, sem credenciais, URL de reunião ou dispositivos.
  Não substituem backup completo nem restauram coleções OBS.
- Treinamento abre uma simulação separada que explica ações sem enviar comandos.

## Aceite necessário no equipamento

1. Fechar configuração pelo X, Escape e Continuar depois, durante e após verificação.
2. Conferir abas/controles em escala 100%, 125% e 150% e tela pequena.
3. Reproduzir vídeo: observar fluidez do preview e testar comandos durante a reprodução.
4. Alternar microfone pelo app e pelo Zoom; confirmar atualização do estado, sem áudio inesperado.
5. Testar câmera IP, USB/captura e fonte existente; desconectar câmera e acionar contingência.
6. Repetir a matriz JWL ↔ Zoom ↔ Salão, com operação manual e automação retomada.
7. Verificar medidores e escuta remota; simular passagem de operador e encerramento.

O ensaio completo em Windows limpo permanece excluído. Suíte e smoke test não substituem os itens acima.
