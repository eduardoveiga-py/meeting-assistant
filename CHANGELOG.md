# Histórico de alterações

## Não lançado — desenvolvimento após 21/09/2026

### Novidades

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

- Núcleo de troca Zoom/JWL validado pelo operador, checkpoint e teste de integridade.
- Escrita atômica da referência da foto, preservando a anterior em falha.
- Aplicação repetida das fontes sem duplicação; não alternar câmera virtual já ativa.

### Limitações e validação

- Câmera IP, captura física, fonte JWL e comportamento nas instalações reais aguardam validação do operador.
- Fonte de janela ambígua é recusada.
- Áudio integrado, instalador, atualizador GitHub e tutorial ilustrado final estão pendentes.
- Testes automatizados verificam regras e comandos; não certificam vídeo real.
- Não há Release pública emitida por este documento.

