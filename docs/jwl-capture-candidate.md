# Candidato: captura nativa da segunda janela JWL

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

## Verificações e pendências

Compilação Windows x64, teste nativo de identidade e integridade de pacote
executados no CI. Testes Python incluem duplicação de títulos, HWND antigo,
ausência de frames, plugin ausente, migração e proteção contra captura do Zoom.
A suíte de regressão e os hashes históricos do contrato de saída continuam no CI.
Nenhum arquivo protegido do núcleo JWL/Zoom foi alterado.

**Validação física pendente**: aplicar o roteiro em [jwl-hwnd-capture.md](jwl-hwnd-capture.md)
no Windows 11 com dois monitores. Sucesso dos testes unitários/CI não comprova
conteúdo, fluidez, Windows+D ou chamada real.

Esta entrega atualiza o código Python e o componente OBS; não recompila o
instalador do aplicativo. Os instaladores antigos continuam sem este lote.
Incluir o novo componente no próximo instalador é uma etapa posterior.
