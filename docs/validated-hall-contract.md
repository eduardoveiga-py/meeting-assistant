# Contrato validado — saída do Salão

Validado pelo operador em 21/09/2026 no commit
48b159b5b819b174011aab143e5772ff6bcbc8b1.

## Comportamento a preservar

- O JWL é o player e sua segunda janela é a saída física padrão do Salão.
- A proteção do JWL funciona mesmo com a automação de cenas pausada.
- Zoom → Salão usa somente a janela secundária do Zoom.
- As duas janelas permanecem abertas; a troca não usa fechamento ou ocultação do Zoom.
- Uma janela Zoom oculta por versão anterior pode ser redescoberta após reiniciar o app.
- A troca controla a prioridade e verifica posição, minimização, cloak e exposição real.
- Quando necessário, a ativação explícita ocorre no pedido do operador, em ambos os sentidos.
- O detector de mídia permanece suspenso durante Zoom e durante o retorno.
- A retomada exige confirmação de que o JWL está efetivamente visível.
- A saída local Zoom não muda a cena do OBS para enviar o próprio Zoom à câmera virtual.
- Texto do Ano significa repouso/Palco; mídia real aciona Mídia e seu fim volta a Palco.
- Preservar a recuperação do JWL após Windows+D.

## Verificação antes de aprovar uma mudança autorizada

1. Automação pausada: repetir três ciclos JWL → Zoom → JWL.
2. Automação ativa: repetir os mesmos ciclos.
3. Verificar início/fim de mídia e Texto do Ano.
4. Verificar Windows+D fora do modo Zoom.
5. Reiniciar apenas o Meeting Assistant e verificar redescoberta do Zoom.
6. Conferir que OBS/câmera virtual não mostram o retorno do próprio Zoom.
7. Conferir telemetria de confirmação e ausência de sucesso falso.

Estes são critérios de regressão. A confirmação atual do usuário não significa que
cada cenário desta lista foi novamente executado nesta data.

## Proteções disponíveis

- Checkpoint independente, mantido no commit validado.
- Teste automático de integridade dos arquivos protegidos, executado pelo Pytest no CI Windows.
- Regras de manutenção em AGENTS.md.
- Testes comportamentais existentes, incluindo falhas e ciclos repetidos.

O teste de integridade é uma barreira contra regressões acidentais, não uma proteção
administrativa de branch. Não foi configurado bloqueio de escrita no GitHub.
