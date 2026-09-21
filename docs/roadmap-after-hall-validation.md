# Próximos passos após validação Zoom/JWL — 21/09/2026

O núcleo de janelas foi validado pelo operador e está congelado. Esta lista organiza
o restante do trabalho; não autoriza implementar sugestões opcionais automaticamente.

## Pendência funcional explicitamente documentada

**Áudio JWL + mesa/microfones → OBS → Zoom**, conforme audio-routing.md:
captura separada, dispositivo de áudio virtual, diagnóstico dos dispositivos e
retorno remoto do Zoom excluído do áudio reenviado. Antes de configurar, confirmar
a mesa/interface e as entradas e saídas disponíveis no Salão.

## Ordem proposta para concluir uma primeira versão utilizável

1. Implementar e validar o áudio acima, sem eco ou áudio duplicado.
2. Ampliar a pré-verificação: monitores, OBS, cenas, câmera virtual, JWL, Zoom e
   dispositivos de áudio; mostrar problemas e ações claras ao operador.
3. Consolidar Iniciar reunião (já existente): reutilizar programas abertos, verificar
   prontidão e exibir etapas concluídas/falhas sem duplicar aberturas.
4. Criar Encerrar reunião com confirmação e escolhas explícitas do que fechar.
5. Preparar configuração do computador do Salão, backup/restauração e, se aprovado,
   perfis por instalação para monitores, cenas e áudio.
6. Testar uma reunião completa e cenários de recuperação no equipamento do Salão.
7. Gerar instalador, atalhos e identificação de versão; testar instalação limpa
   e atualização preservando configurações.
8. Entregar guia curto do operador e procedimento de recuperação/retorno de versão.

Itens 2–8 são uma proposta de organização a confirmar; não foram encontrados como
um cronograma fechado nos documentos atuais.

## Sugestões opcionais para uma fase posterior

- Temporizador de partes/reunião.
- Atalhos configuráveis e controle remoto.
- Avisos e lembretes operacionais.
- Preparação/programação de mídias inspirada em ferramentas como M³, mantendo
  o JWL como player enquanto essa arquitetura continuar sendo a escolhida.

A pesquisa anterior está em reference-projects.md. Este plano não representa uma
nova pesquisa de funcionalidades ou versões desses projetos.
