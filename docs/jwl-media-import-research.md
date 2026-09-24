# Download por idioma e importação no JW Library

Pesquisa de 24/09/2026. Conclusão: baixar mídias e manter o JW Library como reprodutor é viável.
A importação assistida possui um caminho documentado; importação totalmente automática ainda
não foi demonstrada nem implementada neste lote.

## Evidências

- [Documentação oficial de playlists](https://www.jw.org/en/online-help/jw-library/use-playlists/):
  o JWL permite importar uma playlist e adicionar arquivos externos de vídeo, áudio e imagem.
  Isso sustenta um fluxo de selecionar arquivos baixados em Estudo pessoal → Playlists → Importar arquivo.
- [Reaproveitamento de arquivos no Windows](https://www.jw.org/en/online-help/jw-library/using-existing-media-files/):
  o JWL pode verificar mídias de instalações anteriores. A documentação não promete que qualquer
  download em uma pasta arbitrária aparecerá automaticamente na reunião correspondente.
- [Guia do M³](https://sircharlo.github.io/meeting-media-manager/user-guide): organiza mídias por
  data, tipo e seção da reunião e admite conteúdo adicional. Suas funções de download são separáveis
  conceitualmente do player.
- [Código do M³](https://github.com/sircharlo/meeting-media-manager/blob/master/src/helpers/jw-media.ts):
  `processQueuedMeetingDay` resolve o tipo/data, chama `fetchMeetingMediaForDay`, cria seções e substitui
  referências de itens ausentes; `downloadFileIfNeeded` acompanha download e recuperação.
  O processo exige resolver publicações e referências, não apenas baixar todos os MP4 de uma página.

Não encontrei API pública documentada do JWL para inserir arquivos automaticamente em sua biblioteca
ou nas seções nativas de uma reunião. Importar arquivos numa playlist é diferente de reconstruir essas
associações. Gerar um `.jwplaylist` compatível pode ser uma evolução, mas requer validar formato,
versões, ordenação, ações de início/fim e importação real; não tratar um ZIP renomeado como solução.

## Caminho proposto

1. Preferências: idioma da congregação, semana/data, reunião e resolução desejada. Confirmar o idioma
   explicitamente; não inferir do idioma do Windows. Downloads sob demanda inicialmente.
2. Resolver publicações/itens nas fontes oficiais, apresentar a lista esperada e distinguir item ausente,
   indisponível e baixado. Discursos e materiais fornecidos localmente continuam como acréscimos manuais.
3. Baixar fora da reunião, com limite de concorrência, cancelamento, arquivo temporário, validação de
   tamanho/formato e manifesto local. Usar resolução moderada escolhida pelo operador. Não declarar
   uma semana completa quando houver mídia ainda não publicada.
4. Botão **Abrir pasta para importar no JW Library**, lista ordenada e instrução curta para importação
   na playlist. Confirmar importação e reprodução no JWL antes de marcar pronto.
5. Somente depois avaliar geração de playlist ou automação assistida da interface, sem escrever no
   banco de dados, substituir backups ou interferir nas mídias em uso pelo JWL.

Critério de protótipo: uma reunião de meio de semana e uma de fim de semana no idioma escolhido,
arquivos corretos e reproduzíveis offline, ordenação conferida, repetição sem duplicatas e falha de
rede recuperável. Nenhum player independente é necessário. A pesquisa não altera arquivos do JWL.
