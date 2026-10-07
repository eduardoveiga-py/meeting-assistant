# Captura nativa da segunda janela JWL — implementação e validação

Solicitação de 07/10/2026: capturar a janela de saída do JWL quando as duas
janelas têm o mesmo título, preservando automação, áudio e câmera já validados.

## Implementação

- Plugin OBS independente por HWND, reutilizando `libobs-winrt` e suas texturas GPU.
- Validação de processos, gerações, parentesco UWP, classe e monitor secundário.
- Fonte silenciosa separada; captura antiga desativada apenas na cena gerenciada,
  após confirmar a imagem nativa. Nenhuma fonte do operador é apagada.
- Preparação e rediscovery no worker serial do OBS. UI apenas publica snapshots.
- DLL pronta, download automático, pins de SHA-256 e instalação separada da câmera.
- Monitor e outras capturas de janela/jogo bloqueados em Mídias, inclusive em
  cenas/grupos compartilhados. Simulação não desativa a proteção contra feedback.
- Diagnóstico do vínculo nativo e telemetria de mudanças de estado.

## Verificações automatizadas

Compilação Windows x64, teste nativo de identidade e integridade de pacote
executados no CI. Testes Python incluem duplicação de títulos, HWND antigo,
ausência de frames, plugin ausente, migração e proteção contra captura do Zoom.
A suíte de regressão e os hashes históricos do contrato de saída continuam no CI.
Nenhum arquivo protegido do núcleo JWL/Zoom foi alterado.

Na revisão entregue `e9bf684`, a suíte local teve 508 testes aprovados;
CI Windows e build nativo passaram. O pacote `jwl-capture-v1.1` permanece fixado
pelos hashes do manifesto; esta documentação não altera código nem binário.

## Retorno físico de 07/10/2026

Depois de guardar alterações locais, atualizar e executar, o operador confirmou
“Excelente! Funcionou perfeitamente!”. O contexto de testes declarado é
Windows 11 com dois monitores. Registrar **captura correta confirmada no uso
relatado**, sem atribuir ao retorno resultados individuais não informados.

| Cenário | Evidência |
| --- | --- |
| Preparar e usar a captura da segunda janela JWL | Confirmação do operador em 07/10 |
| Títulos duplicados, identidade antiga, ausência de frame e migração | Testes automatizados; nova captura confirmada pelo operador sem diagnóstico detalhado |
| Fluidez medida, Windows+D e três ciclos com automação ativa/pausada nesta revisão | Sem resultados individuais informados; manter roteiro de regressão |
| Reiniciar JWL/OBS ou desconectar monitor nesta revisão | Ensaio específico pendente |

Versões exatas dos aplicativos, FPS e telemetria do ensaio atual não foram enviados.
O aceite não muda os hashes ou o checkpoint do contrato histórico JWL/Zoom.
[Roteiro operacional](jwl-hwnd-capture.md) e
[histórico do incidente](incident-history.md#inc-030--captura-correta-da-segunda-janela-jwl).

Esta entrega atualiza o código Python e o componente OBS; não recompila o
instalador do aplicativo. Os instaladores antigos continuam sem este lote.
Incluir o novo componente no próximo instalador é uma etapa posterior.
