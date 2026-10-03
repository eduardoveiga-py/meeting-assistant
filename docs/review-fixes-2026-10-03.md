# Correções da revisão — 03/10/2026

Base: `b4cd185cc578c5ba0aadc166243faee6b6ad297c` (0.8.1). Este lote entrega
código para executar pelo Python. Não cria release, instalador ou novos binários.
O instalador v0.8.1 existente continua contendo o código anterior.

## O que mudou

| Ponto | Correção | Verificação ainda necessária no Windows 11 |
| --- | --- | --- |
| Guardião | Política única, só com automação ligada; suspenso no Zoom, mídia externa e transições. Retorno explícito continua funcionando pausado. | Windows+D e ciclos JWL/Zoom pausados e ativos |
| Captura de mídias | Captura exclusiva JWL; bloqueia Program inseguro. Preparação desativa itens de monitor nas cenas gerenciadas sem excluir fontes ou alterar cenas pessoais. Grupos compartilhados preservados. | Conferir imagem e ausência de espelhamento |
| Áudio | Perfil comum coerente: mesa + mídias nos dois aplicativos, sem retorno Zoom. Perfil separado opcional envia Zoom somente ao WhatsApp por segundo cabo e Audio Monitor. | Voz/mídia/retorno e ausência de eco |
| Volume | Ganho por fonte, limitador e ordem dos filtros com leitura de confirmação; sem erros de filtro ocultados. Medidores OBS reativados. | Ajustar ganho e ouvir no receptor |
| Microfone Zoom | Rejeita ações coletivas; COM inicializa/encerra no worker; falha de importação libera estado ocupado; cancelamento impede ações tardias. | Testar seu microfone, sem alterar participantes |
| Largura | Botão compacto, política de tamanho flexível e banner compacto. | 100%, 125% e resolução menor |
| Disposição | Inventário fora da GUI, identificação UWP, papéis app/JWL principal, coordenadas relativas à área útil e proteção contra reutilização de PID/janela. | Salvar/reabrir e retirar/reconectar monitor |
| Encerrar | Pausa automação e câmeras; cancela abertura; fecha normalmente inclusive OBS oculto. Informa processos/confirmacões pendentes; sem encerramento forçado. | Confirmar fim da reunião no Zoom quando solicitado |
| Mídia externa | Escolha explícita de janela permitida, captura/cena própria, posição e estilos preservados, rollback de Program apenas enquanto gerenciado, retorno explícito ao JWL. Falha de retorno mantém sensor suspenso. | VLC/navegador e retorno pausado/ativo |
| Foto/OBS local | Resolve todas as interfaces IPv4/IPv6 e nomes no worker. Arquivo local pode ser salvo com OBS offline; aplicação fica pendente. | Aplicar foto usando IP/nome local e conferir a fonte OBS |
| Atualizações | Versões ordenadas; exclui versões inferiores automáticas/draft/prerelease; checksum obrigatório; reunião bloqueia instalação; histórico conectado; modo Python usa Git. Helper espera saída antes de instalar e reabrir. | Futuro ensaio físico do instalador, fora deste lote |
| CI/documentação | CI de push/PR executa testes com limite de tempo e traceback; não compila. Versão de instalador vem do projeto em futura release. Documentação removida de promessas que o código não cumpria. | CI Windows e validação física |

Módulos novos: `hall_policy`, `local_host`, `audio_routes`, `window_inventory`,
`window_layout`, `meeting_shutdown`, `obs_capture_safety`, `obs_external_media`,
`app_layout` e `update_dialog`. Serviços não manipulam widgets e a GUI recebe sinais.
O caminho nativo de câmera, a ponte OBS e o renderer do preview permanecem intactos.

## Proteção do núcleo

O checkpoint histórico e a tabela `validated-hall-baseline.json` foram preservados.
A única alteração no serviço protegido de troca JWL/Zoom é a função de política,
com a expectativa correspondente no teste. Os hashes candidatos ficam separados
em `hall-policy-candidate.json`, marcados **physical_pending**. Não equivalem a
aceite físico e não substituem as assinaturas históricas.

## Atualizar para testar

Feche o app. Na pasta do projeto, use:

```powershell
git switch main
git pull --ff-only
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

Se Git indicar alterações locais, preserve-as antes de reconciliar; não use
`reset --hard` para apagar trabalho. O launcher usa Python 3.12 e prepara as
bibliotecas. Os componentes nativos já publicados continuam sendo verificados
pelo manifesto; esta entrega não exige compilação.

Antes de preparar fontes, exporte a coleção de cenas e o perfil do OBS. Os testes
abaixo devem ser feitos fora de uma reunião, com a mídia e os cabos habituais.

## Testes prioritários com segunda tela

1. **Fonte JWL:** em Ajustes → Texto do Ano/fontes OBS, prepare a janela JWL em
   Mídias. A captura deve apontar à janela secundária, não ao monitor inteiro.
   As capturas antigas usadas nas cenas do app ficam desativadas; cenas pessoais
   e fontes não são excluídas. Confira a imagem completa no OBS.
2. **Guardião:** abra o app com automação pausada. Ele não deve disputar janelas.
   Ligue a automação e use Windows+D: JWL deve retornar ao salão. Pause e repita:
   não deve haver restauração periódica automática.
3. **Zoom:** execute três ciclos Zoom → Salão → JWL com automação pausada e três
   com ela ligada. A janela secundária Zoom deve continuar existindo. O retorno
   deve confirmar o JWL; seu próprio Zoom não deve ser capturado na câmera OBS.
4. **Mídia JWL:** Texto do Ano deve significar repouso/Palco. Início de mídia
   muda para Mídias; término retorna a Palco. Repita após Windows+D.
5. **Mídia externa:** abra VLC e clique Mídia Externa. Escolha sua janela,
   confira captura/cena exclusiva no OBS e exibição no salão. Pare: Program
   anterior e disposição do VLC devem retornar; JWL deve ser confirmado visível.
   Repita pausado e ativo. Uma falha de retorno deve ser informada e manter a
   detecção suspensa até nova tentativa, sem sucesso falso.
6. **Foto:** capture/atualize Texto do Ano, confirme e salve. Confira no OBS o
   arquivo correto. Repita com OBS desconectado: a foto deve continuar salva,
   com aplicação pendente. Reconecte e aplique a foto salva. Teste host loopback
   e o IP/nome deste mesmo PC.
7. **Disposição:** coloque app à esquerda e JWL principal à direita. Em Ajustes,
   salve a disposição, feche/reabra e inicie reunião. JWL secundário não deve ser
   movido. Teste também desconectar o monitor antes de abrir: app deve continuar
   dentro da área útil, sem botões atrás da barra de tarefas.

## Áudio e operação

8. **Perfil comum:** confirme CABLE Input no monitoramento OBS e CABLE Output no
   microfone de Zoom/WhatsApp. Prepare, selecione mesa + JWL e ative. Teste voz
   e mídia nos dois receptores. Zoom deve permanecer sem captura neste perfil.
   Aumente ganho em passos pequenos e confira medidores e receptor. O limitador
   não corrige saturação na entrada física.
9. **Perfil separado, opcional:** somente após instalar segundo cabo + Audio
   Monitor e reiniciar OBS. Selecione segundo perfil, outro destino virtual e
   áudio Zoom. Zoom mantém primeiro cabo como microfone; WhatsApp usa o segundo.
   Teste um comentário Zoom ouvido no WhatsApp e ausência de retorno ao Zoom.
   O botão WhatsApp deve silenciar apenas seu retorno nas caixas do salão.
10. **Mic Zoom:** alternar seu microfone e conferir o estado no Zoom. Botões de
    silenciar/ativar todos os participantes não podem ser acionados pelo app.
11. **Encerrar:** clique Encerrar. Automação e câmeras devem parar. Confirme o
    encerramento do Zoom se ele pedir. Um programa ainda aberto deve ser
    apresentado como pendente; o app não força seu fechamento.
12. **Atualizações:** Ajustes → Atualizações e versões anteriores deve mostrar
    notas e permitir nova tentativa se a consulta falhar. Nesta execução Python,
    a ação apresenta Git/run.ps1; não instala EXE. Uma versão inferior não gera
    banner de atualização. Instalação e restauração no executável ficam para
    ensaio futuro com artefatos verificados; OBS, Zoom e WhatsApp precisam estar
    fechados para liberar os componentes da câmera.

Para relatar falha: informe número do teste, horário, versão do OBS/Zoom/JWL,
estado da automação, mensagem completa do app e diagnóstico textual/telemetria.
Não publique credenciais ou links privados. Este ambiente não acessa o PC do
operador nem valida áudio/vídeo recebidos por um dispositivo remoto.


## Verificação automatizada

A suíte local usa Python 3.12 e Qt offscreen, com serviços Win32/OBS simulados.
Testes incluem contratos e falhas parciais; nenhuma chamada real é iniciada nos
aplicativos do operador. O CI Windows executa a mesma suíte sem builds nativos.
Na execução local deste lote, os 363 testes passaram; Ruff e a conferência de
espaços do diff também passaram. O registro está em
[review-fix-validation.json](review-fix-validation.json). Confira o resultado
Windows em Actions para o commit de entrega. O teste físico do roteiro continua
sendo necessário antes do uso em reunião.
