# Correção candidata — maximização do JWL na abertura

Pedido explícito do operador em 21/09/2026: o app cria uma faixa superior no JWL a cada
inicialização. Sessão MA-20260921-160931-73CD registra `normalized_maximized` imediatamente
após identificar a janela. A rotina forçava SW_SHOWMAXIMIZED e SetWindowPos antes de avaliar
se a janela precisava de recuperação. A correção remove essa chamada incondicional;
a recuperação existente de janelas minimizadas, cobertas, ocultas ou deslocadas permanece.

Esta é uma hipótese causal apoiada pelo código e pelos registros, ainda sem confirmação
visual no equipamento. A versão validada e o checkpoint permanecem em
48b159b5b819b174011aab143e5772ff6bcbc8b1.

**O teste test_validated_hall_engine_is_unchanged deve sinalizar a alteração do guardião.**
Não atualizar hashes, ignorar o teste ou considerar o novo núcleo validado antes do ensaio.
Testes funcionais verificam ausência de maximização no início e permanência da recuperação.

## Ensaio necessário

1. Fechar o Meeting Assistant e reabrir o JWL uma vez para descartar o estado de maximização
   imposto pela versão anterior. Conferir a saída sem faixa antes de abrir o app atualizado.
2. Abrir e reabrir só o app: a saída deve continuar igual, sem faixa superior.
3. Capturar, confirmar e salvar nova foto; verificar que a data da captura mudou e o OBS
   usa a nova imagem. Aplicar foto já salva apenas reaplica o arquivo anterior.
4. Windows+D, Zoom → Salão → JWL, reproduzir/parar mídia; testar ativo e pausado.
5. Só após confirmação do operador, atualizar a referência validada de forma documentada.

Outro bloqueio identificado: WorkerW aparece como superfície acima do JWL, mesmo com saída
visível. Assim como a barra de tarefas, geometria dessas superfícies do shell não prova
oclusão; a prévia pode ser exibida, mas exige conferência humana. Janelas de aplicativos
continuam bloqueando. Nenhuma captura é salva automaticamente.
