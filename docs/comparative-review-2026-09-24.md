# Pesquisa comparativa e plano de conclusão — 24/09/2026

## Parecer

O Meeting Assistant deve terminar a versão atual como **coordenador da operação de JW Library, OBS e Zoom no Windows**. O diferencial é manter a apresentação oficial no JW Library e ajudar o operador com saída física, cenas, áudio e recuperação. Transformá-lo agora em outro player, downloader ou editor de macros aumentaria a superfície de falhas sem resolver as pendências mais importantes.

Minha avaliação é de um produto em consolidação: há um núcleo validado pelo operador, testes e uma distribuição publicada, mas isso não equivale a validação de todos os computadores, drivers e versões dos aplicativos externos.

## Método e limites

Analisei arquivos de implementação, testes, documentação e relatos públicos. Não executei os aplicativos de terceiros. “Acerto” abaixo significa uma decisão concreta observável; “falha” significa um problema documentado ou um risco inferido do código, identificado como tal. Quantidade de estrelas não foi usada como evidência de confiabilidade. Um issue fechado não prova que o problema foi resolvido em todas as versões.

Referências de código consultadas:

| Projeto | Referência examinada | Escopo lido |
| --- | --- | --- |
| Meeting Assistant | `3bd97cd4b25fbe6a58a3f5a7ea43fbc3075ecec2`, com comparação da `v0.5.0` | Configuração, telemetria, integração principal, UI de ajustes, OBS/áudio, testes e distribuição |
| JwlMediaWin | `b0bb10ac9f2dd1bb8b2452dd0ce3abf427bab29b` | `Fixer.cs`, `FixerRunner.cs`, README |
| OnlyM | `0a2938b0af3d6c76ee5315a69a53b42eba55cd18` | `IMediaElement.cs`, `MediaWindowPositionHelper.cs`, issue #195 e discussão #401 |
| Meeting Media Manager (M³) | `1a544395b94db7e382776ca0a92aca1df5f5c01a` | `src/helpers/obs.ts`, `src/helpers/zoom.ts`, README e guia oficial |
| Advanced Scene Switcher | `abc8c3708f88439f073da57cea2223355bff2f08` | `macro-condition-media.cpp`, documentação do autor no OBS e issue #1562 |

Os hashes identificam os snapshots retornados pelo GitHub nesta consulta. O levantamento é dirigido às integrações relevantes, não uma auditoria completa dos quatro repositórios. Nenhum código desses projetos foi copiado para o Meeting Assistant.

## 1. JwlMediaWin: o paralelo mais direto

**Caminho:** utilitário pequeno, especializado em impedir que a janela secundária do JW Library desapareça ao usar outros aplicativos. Localiza elementos por UI Automation, verifica padrões disponíveis, dá foco à janela e usa a transformação de janela do Windows, seguida de ajustes Win32.

**Acertos observados:** cache dos elementos encontrados; invalidação quando o elemento deixa de existir; confirmação do foco antes do atalho; intervalo de 10 segundos antes de repetir a conversão. Essa espera evita que uma conversão lenta seja imediatamente desfeita pelo mesmo comando. O loop também varia o intervalo de procura conforme a situação.

**Fragilidades documentadas no próprio código:** houve mudança da barra de título em janeiro de 2021; existe uma espera de 500 ms porque reposicionar imediatamente podia deixar a janela no monitor principal. Isso mostra o custo real de depender do comportamento visual de outro aplicativo.

**Comparação:** seu app já vai além desse utilitário ao coordenar recuperação, sensor e alternância com Zoom. A lição é conservar o núcleo aprovado e manter testes para foco, DPI, monitor desconectado e janelas recriadas. Instalar dois guardiões simultâneos seria introduzir disputa pela mesma janela.

**Decisão:** adotar a disciplina de confirmação, espera e recuperação; não substituir nem refatorar o núcleo congelado nesta etapa.

Fontes: [Fixer.cs](https://github.com/AntonyCorbett/JwlMediaWin/blob/b0bb10ac9f2dd1bb8b2452dd0ce3abf427bab29b/JwlMediaWin.Core/Fixer.cs), [FixerRunner.cs](https://github.com/AntonyCorbett/JwlMediaWin/blob/b0bb10ac9f2dd1bb8b2452dd0ce3abf427bab29b/JwlMediaWin.Core/FixerRunner.cs), [proposta do projeto](https://github.com/AntonyCorbett/JwlMediaWin).

## 2. OnlyM: controlar o player dá eventos, mas traz codecs e renderização

**Caminho:** apresentação de mídia em uma janela própria. A interface `IMediaElement` separa o uso do player de sua implementação e oferece eventos de abertura, fechamento, término, falha e posição. Há implementações distintas para mecanismos de reprodução.

**Acerto:** quem controla o player pode receber eventos de reprodução, sem deduzir todo o estado pela imagem da tela. Isso facilita distinguir pausado, terminado e falhou.

**Problema documentado:** o issue #195 descreve perda de quadros no início de certos vídeos H.264 no monitor secundário com Media Foundation/WPF. O código de posicionamento contém uma solução condicionada que faz a janela ultrapassar um pixel do monitor principal, compensando a margem. A discussão #401 reúne relatos de diferenças de desempenho e reprodução; são relatos de máquinas específicas, não um benchmark geral.

**Comparação:** seu sensor visual é uma adaptação à decisão de preservar o JW Library. Um player próprio poderia dar sinais mais claros, mas também transferiria para seu projeto o suporte a codecs, GPU, legendas e renderização. O código do OnlyM evidencia esse custo.

**Decisão:** manter o JW Library. Se houver uma necessidade futura de reproduzir arquivos externos diretamente, usar um adaptador isolado com estados explícitos e testes, como evolução separada, sem fundir esse experimento ao núcleo atual.

Fontes: [interface do player](https://github.com/AntonyCorbett/OnlyM/blob/0a2938b0af3d6c76ee5315a69a53b42eba55cd18/OnlyM/MediaElementAdaption/IMediaElement.cs), [posicionamento e workaround](https://github.com/AntonyCorbett/OnlyM/blob/0a2938b0af3d6c76ee5315a69a53b42eba55cd18/OnlyM/Services/MediaWindowPositionHelper.cs), [issue #195](https://github.com/AntonyCorbett/OnlyM/issues/195), [discussão #401](https://github.com/AntonyCorbett/OnlyM/discussions/401).

## 3. M³: a referência de produto mais próxima

**Caminho:** aplicativo Electron/TypeScript/Vue que gerencia, baixa e apresenta mídias, com integrações opcionais de OBS e Zoom. Seu escopo de conteúdo é maior que o do Meeting Assistant.

**Acertos no código OBS:** verificação do estado conectado antes das chamadas; uma promessa compartilhada impede loops concorrentes de conexão; tentativas limitadas com espera; ao esgotar tentativas, o estado é liberado para permitir nova conexão. Os comentários explicam duas falhas anteriores: enviar solicitações antes da identificação do WebSocket e ficar permanentemente em “conectando”. Há arquivos de testes dedicados ao OBS na árvore do projeto.

**Limite na integração Zoom:** `triggerZoomScreenShare(startSharing)` envia o mesmo atalho configurado para iniciar/parar; o parâmetro altera o atraso e a mensagem, não confirma o estado real do compartilhamento. Há tentativas adicionais de foco em 500 e 1.000 ms. Minha inferência: um comando perdido ou intervenção manual pode deixar a intenção do app diferente do estado do Zoom. Isso não é equivalente ao seu recurso Zoom → Salão, que posiciona a janela dos participantes localmente.

**Comparação:** aproveitar a apresentação de estados e a separação entre “comando solicitado” e “resultado confirmado”. Seu controlador OBS já possui fila, reconexão e consultas, portanto não é preciso reescrever o cliente. A próxima melhoria deve ser provar o comportamento em desconexões e comandos pendentes.

**Áudio:** o guia reconhece que a integração visual com OBS não transmite automaticamente o som ao Zoom. Isso coincide com sua separação explícita de VB-CABLE/monitoramento. As telas e recomendações de áudio de guias podem envelhecer; não repliquei configurações antigas como receita universal.

Fontes: [conexão OBS](https://github.com/sircharlo/meeting-media-manager/blob/1a544395b94db7e382776ca0a92aca1df5f5c01a/src/helpers/obs.ts), [atalho Zoom](https://github.com/sircharlo/meeting-media-manager/blob/1a544395b94db7e382776ca0a92aca1df5f5c01a/src/helpers/zoom.ts), [guia mantido pelo projeto](https://sircharlo.github.io/meeting-media-manager/user-guide).

## 4. Advanced Scene Switcher: referência para estados, não outro controlador

**Caminho:** plugin dentro do OBS, organizado em condições e ações de macros. A condição de mídia consulta estados explícitos como reproduzindo, abrindo, carregando, pausado, parado, terminado e erro, além de tempo e duração.

**Acerto técnico:** no término de playlist, o código combina estados consecutivos e sinais de próximo item. Isso evita tratar toda transição entre itens como fim definitivo. É uma referência útil para desenhar testes de borda e temporização.

**Limite:** esses estados pertencem a fontes de mídia que o OBS conhece. Uma captura de janela do JW Library não ganha automaticamente o estado do player externo. Logo, instalar o plugin não resolve sozinho o problema do seu sensor.

**Relato de falha:** o issue #1562 descreve crash com macros, gravação e transmissão simultâneas em uma combinação específica de versões. Ele está fechado, mas o relato isolado não permite atribuir todos os crashes ao plugin nem concluir que versões atuais falham. A lição aplicável é testar funções simultâneas e manter clara a responsabilidade por cada cena.

**Decisão:** aproveitar os casos de teste e os conceitos de estados. Não introduzir macros concorrentes para controlar as mesmas cenas durante a reunião.

Fontes: [condição de mídia](https://github.com/WarmUpTill/SceneSwitcher/blob/abc8c3708f88439f073da57cea2223355bff2f08/plugins/base/macro-condition-media.cpp), [documentação do autor no OBS](https://obsproject.com/forum/resources/advanced-scene-switcher.395/), [relato #1562](https://github.com/WarmUpTill/SceneSwitcher/issues/1562).

## 5. Outras fontes e o que não concluir delas

O manual do **SoundBox 3.1** registra o encerramento do suporte ao final de 2018 e recomenda a transição para JW Library, com ferramentas separadas para necessidades adicionais. Isso é uma mudança deliberada de escopo, não prova de fracasso técnico. Para nosso projeto, é um argumento para complementar o JW Library e evitar manter uma segunda plataforma completa de mídia. [Manual original, página 1 do conteúdo](https://cv8.org.uk/soundbox/SoundBox.pdf).

O **guia oficial do OBS para captura de áudio por aplicativo** reconhece limitações de compatibilidade e a possibilidade de recorrer a outro método de captura. Portanto, “fonte criada no OBS” não pode ser exibido como “áudio confirmado no Zoom”. [Guia OBS](https://obsproject.com/kb/application-audio-capture-guide).

A **documentação do PyInstaller** distingue executável único de distribuição em pasta. Na `main`, a configuração era de executável único e o workflow/instalador esperavam uma pasta; a `v0.5.0` corrigiu caminhos fora da `main`. A correção desta revisão padroniza distribuição em pasta, adequada a um instalador, com teste do executável gerado. [Documentação](https://pyinstaller.org/en/stable/spec-files.html), [comparação das referências do app](https://github.com/eduardoveiga-py/meeting-assistant/compare/main...v0.5.0).

## Alterações desta revisão

- Configurações: validação estrita de tipos, limites de portas e nomes de cenas; recuperação seletiva; cópia identificada do arquivo inválido; aviso de recuperação.
- Diagnóstico: gravação local por padrão; envio por Git exige nova opção explícita e destino preenchido, inclusive ao migrar configurações antigas; falhas de inicialização e gravação não interrompem a operação; fila limitada.
- Privacidade: cobertura adicional de credenciais em URLs e mensagens; interface deixa claros os limites da remoção de segredos e das capturas; exportação ZIP local só de diagnóstico textual, sem screenshots, configurações ou histórico Git.
- Destino: clone existente não é redirecionado automaticamente a outro repositório; evita levar histórico anterior a um novo destino sem revisão.
- Distribuição: spec com caminhos absolutos derivados de sua localização, recursos e metadados de versão; build comum ao CI e release; versão do instalador derivada do pacote; validação de tag; testes antes de publicação; smoke test sem iniciar serviços operacionais; checksums sem incluir o próprio arquivo de checksums.
- Regressão: novos testes para configurações inválidas, falhas de disco, fila cheia, exportação e ausência de rede no modo local.

Os arquivos protegidos, fingerprints e checkpoint permanecem intactos. Alterações em `main.py` e `main_window.py` se limitam à integração de diagnóstico e aviso de configuração, sem mudar guardiões, controle de janelas, sensor ou callbacks de alternância.

## O que falta para concluir a versão operacional

| Ordem | Entrega | Critério objetivo de conclusão |
| --- | --- | --- |
| 1 | Integrar esta revisão | CI com lint, testes, build, smoke test e instalador aprovados no mesmo commit; revisar diff do núcleo protegido |
| 2 | Fechar pré-verificação | Diferenciar instalado, conectado, configurado e confirmado pelo operador; nenhum indicador verde de áudio baseado apenas na existência da fonte |
| 3 | Concluir áudio no equipamento atual | Escuta remota confirma voz + JWL + mídia externa, sem eco/duplicação; caminho de emergência documentado; definir necessidade real de estéreo |
| 4 | Concluir câmera IP | Confirmar imagem, reconexão e ausência de áudio duplicado; registrar modelo, stream e versões compatíveis sem publicar credenciais |
| 5 | Matriz de recuperação | Ensaiar OBS indisponível/reiniciado, Zoom recriado, monitor desconectado, reinício no meio de vídeo e configurações corrompidas; guardar resultado por versão |
| 6 | Fechar distribuição e suporte | Documentar atualização manual preservando ajustes, retorno à versão anterior, dependências e avisos de distribuição; conferir instalação/desinstalação quando o ensaio for retomado |
| 7 | Guia de uma página | Operador consegue preparar, iniciar, interromper e voltar à cena segura sem consultar documentação de desenvolvimento |

**Fora desta execução por solicitação do usuário:** ensaio completo em Windows limpo. Continua sendo uma pendência declarada para certificar distribuição ampla; não é substituído pelo smoke test de build.

**Depois da versão operacional:** perfis, atualização automática segura, atalhos globais e novos players só devem entrar com necessidade demonstrada. Atualização automática deve ter verificação, rollback e nunca interromper reunião; não é requisito para concluir a primeira versão com atualização manual documentada.

## Critério de “finalizado”

Versão operacional significa: instalar/atualizar de forma documentada; recuperar configurações sem perder evidência; abrir mesmo sem diagnóstico/rede; indicar o que está realmente confirmado; manter saída segura; possuir procedimento curto de recuperação. Não significa automatizar cada configuração física possível.

As verificações físicas de áudio, câmera e telas precisam de observação humana no equipamento. Nesta revisão automatizada, esses itens continuam pendentes, sem declaração de certificação.
