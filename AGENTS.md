# Regras de manutenção — Meeting Assistant

## Núcleo validado e congelado pelo operador

Em 21/09/2026 Eduardo confirmou que a troca Zoom → Salão → JW Library funciona
como deveria e pediu explicitamente para preservar esse comportamento.

- Versão validada: 02094d80aa45ab0088d271691122839da759b1ee.
- Recuperação: checkpoint/zoom-jwl-validated-20260921.
- Arquivos protegidos: docs/validated-hall-baseline.json.
- Contrato e testes manuais: docs/validated-hall-contract.md.

Não alterar, refatorar ou substituir esses arquivos para implementar outras funcionalidades.
Não atualizar os fingerprints apenas para tornar o CI verde. Uma futura correção nesse
núcleo requer pedido explícito do usuário que autorize esse novo trabalho, explicação do
impacto, testes de regressão e nova confirmação nos dois monitores antes de atualizar
a versão considerada validada. Nunca mover o checkpoint para outra versão.

Preservar também a integração em main.py e ui/main_window.py: guardiões, callbacks,
sinais, ativação das janelas, pausa e retomada do sensor. Esses arquivos podem receber
outras funções, mas não alterações no contrato protegido sem a autorização acima.

Implementar áudio, pré-verificação, perfis e instalador em módulos separados, usando
as interfaces existentes. Não mudar a arquitetura de saída para facilitar outra função.
