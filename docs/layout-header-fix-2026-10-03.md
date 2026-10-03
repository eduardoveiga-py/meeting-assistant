# Correção do cabeçalho — 03/10/2026

Base: `392bd6c5fdb78150a69f9ec0e7b32066012f2c9c`. Entrega de código Python.

## Por que os testes anteriores passaram

O ajuste de largura deixou os rótulos do título sem largura mínima. Uma mola
separada (`addStretch`) absorvia o espaço restante da linha, em vez de reservá-lo
ao título. O Qt considerava os rótulos visíveis, mas lhes atribuía largura zero.
O subtítulo quebrava em muitas linhas, aumentava a altura do cabeçalho e esticava
o indicador de automação. Isso consumia o espaço disponível para a prévia.

Os testes anteriores conferiam ausência de rolagem, encaixe dos botões e estados
dos serviços. Essas propriedades continuavam passando nesse layout. Faltava
conferir a geometria e a exposição dos textos do cabeçalho, a altura do indicador
e o espaço reservado à prévia. A aprovação de 364 testes não validava esses
aspectos; houve uma regressão no ajuste e uma lacuna na verificação.

## Correção e evidências

- A coluna de título recebe a largura restante; a mola separada foi removida.
- Título e subtítulo podem quebrar linhas dentro da largura atribuída.
- O indicador de automação usa sua altura natural, alinhado ao centro da linha.
- Abaixo de 560 pixels lógicos de altura, margens e intervalos ficam menores;
  fontes e alturas dos botões são preservadas. Os intervalos normais voltam ao
  aumentar a janela. A verificação nativa em Full HD/200% detectou a necessidade
  dessa adaptação, mantendo o requisito de não esconder controles ou exigir rolagem.
- Uma regressão reproduziu a largura zero antes do patch e passou depois dele.
- Casos ativos e pausados verificam títulos expostos, indicador compacto, prévia
  com altura útil e controles dentro da janela em diferentes alturas.
- Processos Qt separados renderizam a janela real em 100%, 125%, 150% e 200%,
  usando uma área útil Full HD convertida em coordenadas lógicas. OBS, janelas
  externas e o conteúdo de vídeo são simulados; nenhuma chamada é iniciada.
- No Windows, essas renderizações usam o plugin nativo do Qt e verificam a
  presença de letras na fonte. O plugin offscreen usado na primeira tentativa
  gerava quadrados no lugar das letras e métricas que não representavam a tela
  real. No Linux, a verificação mantém offscreen com suas fontes disponíveis.
- O CI Windows guarda as quatro imagens em **Artifacts → operator-layout** para
  inspeção visual. O resultado da execução deve ser consultado em Actions para
  o commit desta correção. Não há compilação de câmera, executável ou instalador.

A alteração não modifica o guardião, a troca JWL/Zoom, o áudio ou o fluxo nativo
de vídeo. Ela muda a distribuição de espaço dos widgets da tela principal.

## Conferir no computador

Feche o app, atualize o projeto e execute novamente:

```powershell
git pull --ff-only
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

Confira que **Meeting Assistant** e a mensagem/atalho do Texto do Ano aparecem,
que o indicador fica pequeno no canto superior direito e que a prévia recupera
seu espaço. Repita com automação pausada e ativa, redimensione a altura e reabra
o app com a disposição salva. Use sua escala habitual do Windows; não é preciso
reduzi-la para contornar o defeito.

As renderizações automatizadas não substituem essa conferência na máquina real.
