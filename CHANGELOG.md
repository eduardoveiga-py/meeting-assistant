# Histórico de alterações

## Não lançado — desenvolvimento após 21/09/2026

### Novidades

- Assistente unificado de configuração com revisão por versão no executável, diagnóstico,
  instalação consentida OBS/Zoom via WinGet e preparação autenticada de WebSocket com backup.
- Formulários de ajustes e foto/fontes integrados no assistente; ensaio real reservado para a Release.

- Configuração de câmera IP para Palco e padronização de Texto do Ano, Palco e Mídias.
- Opção de inicialização OBS na bandeja no login do Windows.
- Captura e prévia da foto do Texto do Ano, confirmação manual do ano e gravação versionada.
- Aviso de foto ausente, inválida ou de outro ano; aplicação pendente ao reconectar OBS.
- Preparação da fonte de imagem e da captura específica da janela JWL.
- Verificação de fontes e confirmação da câmera virtual, inclusive com OBS já aberto.

### Melhorias

- Documentação inicial, roteiro ampliado, guia de configuração e critérios de teste.
- Fonte de captura JWL com correspondência exata; sem fallback para monitor/Zoom.
- Referência do detector separada da foto de apresentação.

### Correções e estabilidade preservada

- Captura verifica a ordem das janelas a partir do HWND JWL já identificado, sem exigir
  que a saída UWP apareça no EnumWindows. Percurso limitado, detecção de ciclos e diagnóstico.

- Correção candidata do guardião: remover maximização incondicional do JWL na abertura;
  inspecionar antes de recuperar. Exige nova validação física, sem atualizar o baseline.
- WorkerW/Progman tratados como superfícies internas do shell na prévia confirmada da foto.
- Mensagem de aplicação ao OBS distingue arquivo existente de uma nova captura.

- Retângulo informado pelo Explorer para a barra de tarefas não bloqueia mais a prévia
  do Texto do Ano; confirmação visual continua obrigatória. Outras janelas ainda bloqueiam.

- Verificação visual de sobreposição por ordem das janelas, substituindo teste de ponteiro
  que pode ignorar janelas desabilitadas; diagnóstico identifica classe/retângulo do bloqueador.

- Confirmação, botão de salvar e resultado da foto sempre visíveis, fora da rolagem.
- Nova prévia identificada como não salva; falha de recaptura invalida a prévia anterior.
- Captura recusa bordas expostas e registra retângulos de monitor, janela, cliente e DWM.
- Investigação da faixa física do JWL pendente das novas medidas; guardiões preservados.

- Núcleo de troca Zoom/JWL validado pelo operador, checkpoint e teste de integridade.
- Escrita atômica da referência da foto, preservando a anterior em falha.
- Aplicação repetida das fontes sem duplicação; não alternar câmera virtual já ativa.

### Limitações e validação

- Câmera IP, captura física, fonte JWL e comportamento nas instalações reais aguardam validação do operador.
- Fonte de janela ambígua é recusada.
- Áudio integrado, atalhos F1–F10, instalador, atualizador GitHub e tutorial ilustrado final estão pendentes.
- Roteamento de áudio decidido: mesa e aplicativos no OBS → VB-CABLE → microfone Zoom,
  excluindo retorno remoto e impedindo duplicação do áudio já presente na mesa.
- Testes automatizados verificam regras e comandos; não certificam vídeo real.
- Não há Release pública emitida por este documento.

