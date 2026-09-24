# Recuperação, atualização e aceite — 0.5.1

## Registro de validação

Em 24/09/2026, o responsável confirmou que o passo de áudio e câmera IP foi testado e funciona no equipamento atual. Não foram informados modelos dos dispositivos, versões dos aplicativos nem resultados individuais de cada fonte. Esse aceite não se estende automaticamente a outros computadores ou aos cenários de falha abaixo.

O núcleo JWL ↔ Zoom ↔ Salão mantém o aceite de 21/09/2026 e seus arquivos protegidos. A versão 0.5.1 está preparada no código; publicação de release e ensaio físico de atualização são etapas distintas. O ensaio completo em Windows limpo está excluído desta entrega a pedido do responsável.

## Matriz de recuperação

Execute sem público, com a configuração habitual e uma mídia conhecida. Para cada linha registre data, versão do app/OBS/Zoom/JWL, monitores, ação, resultado e horário da sessão de diagnóstico. Testes automatizados de estados não substituem essa observação física.

| Cenário | Procedimento e resultado esperado | Recuperação se não atingir o resultado | Evidência atual |
| --- | --- | --- | --- |
| Reiniciar OBS | Com automação pausada, fechar e abrir OBS; verificar reconexão, cenas, câmera virtual e áudio recebido | Conferir WebSocket; iniciar câmera virtual; revisar dispositivos e fontes antes de retomar | Ensaio físico específico pendente |
| Reiniciar Zoom | Voltar ao JWL; fechar Zoom; entrar novamente e repetir Zoom → Salão → JWL | Habilitar dois monitores; confirmar as duas janelas; selecionar câmera/microfone corretos | Ensaio físico específico pendente |
| Desconectar monitor | Pausar automação; desconectar e reconectar a tela; conferir que o app identifica a tela correta | Restabelecer área de trabalho estendida, selecionar tela do Salão e verificar JWL antes de retomar | Ensaio físico específico pendente |
| Abrir app durante vídeo | Iniciar vídeo no JWL com app fechado; abrir app e observar cena, continuidade da mídia e tela | Pausar automação e operar cenas manualmente; registrar falha sem recalibrar durante o vídeo | Ensaio físico específico pendente |
| Windows+D e redescoberta | Fora de Zoom → Salão, usar Windows+D; reiniciar somente o app e repetir alternância | Conferir tela física e janela secundária; registrar horário se não recuperar | Coberto pelo roteiro do núcleo validado; repetir após atualização |
| Áudio e câmera IP | Conferir voz/mídia e imagem no equipamento habitual | Revisar fonte, roteamento e conectividade da câmera | Aceite do responsável em 24/09/2026 |

Uma falha de OBS pode impedir até a seleção de Palco pelo app. Nessa situação, restaure o OBS e confira a saída física; o botão de cena segura não garante uma imagem quando a conexão está indisponível.

## Atualizar

1. Fora de uma reunião, guarde o instalador da versão atualmente funcional. Para a nova versão, use uma release publicada do repositório; artefatos de CI servem para avaliação e podem expirar.
2. Feche o Meeting Assistant e faça uma cópia privada de toda a pasta `%APPDATA%\MeetingAssistant`, incluindo ajustes e imagens. Exporte também perfil e coleção de cenas pelo OBS antes de mudar fontes. Não publique esse backup: ele pode conter senhas e links de reunião.
3. Quando houver checksum publicado, compare-o com `Get-FileHash .\MeetingAssistant-Setup-0.5.1.exe -Algorithm SHA256`. O número do arquivo deve corresponder à release escolhida.
4. Execute o instalador no mesmo usuário e diretório. Não apague configurações para atualizar. O instalador não atualiza OBS, Zoom, JWL nem drivers de áudio.
5. Abra o app, revise o assistente de configuração e execute **Verificar ambiente novamente**. Uma cena existente ou câmera virtual ativa não comprova áudio e imagem no Zoom.
6. Faça o ciclo habitual JWL → Zoom → JWL, voz/mídia e as linhas da matriz aplicáveis. Só então use em reunião. Registre a versão e o resultado.

## Voltar à versão anterior

1. Feche o app. Preserve separadamente os dados atuais e exporte diagnóstico textual, se necessário, para analisar a falha.
2. Execute o instalador anterior no mesmo diretório. Se for necessário desinstalar primeiro, mantenha o backup privado fora da pasta de instalação.
3. Com o app fechado, restaure a cópia de `%APPDATA%\MeetingAssistant` feita antes da atualização. Não misture arquivos de backups diferentes. Restaurar apenas o executável não reverte ajustes.
4. Se você alterou o OBS, importe o perfil e a coleção de cenas anteriores. A reversão do Meeting Assistant não desfaz configurações dos aplicativos externos.
5. Abra e repita a pré-verificação e o ciclo curto de operação. A compatibilidade de downgrade depende desse ensaio; não há atualizador nem rollback automático.

## Critério de conclusão

Código e instalador precisam passar pelo CI Windows, incluindo teste de integridade do núcleo, suíte, lint e smoke test do executável. O aceite de áudio/câmera já foi recebido. A matriz acima e o ensaio de atualização/retorno no equipamento real permanecem como verificações operacionais documentadas, sem exigir o Windows limpo excluído do escopo.
