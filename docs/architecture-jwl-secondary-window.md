# Arquitetura — saída secundária do JW Library

## Decisão

O JW Library continua sendo o player e a interface de operação de mídia. O Meeting Assistant não cria uma segunda camada de reprodução própria para o fluxo principal.

A saída do Salão é a janela secundária nativa do JW Library. O Meeting Assistant identifica, protege e observa essa janela, enquanto o OBS continua sendo a fonte de verdade das cenas.

## Fonte de verdade por domínio

- **Mídia e apresentação física:** janela secundária do JW Library.
- **Cenas e transições:** OBS.
- **Orquestração da reunião:** Meeting Assistant.
- **Monitor do Salão:** configuração persistida; por padrão, primeira tela não principal.

## Identificação da janela secundária

Não confiar apenas em `ApplicationFrameHost.exe`, pois o mesmo host também executa outros apps UWP.

Sinais usados, em ordem de força:

1. título específico da segunda tela, como `Second Display ‎- JW Library` (normalizando marcas Unicode invisíveis);
2. `ApplicationFrameWindow` contendo um filho `Windows.UI.Core.CoreWindow` identificado como JW Library;
3. ausência de title bar visível;
4. estado topmost;
5. fullscreen/ocupação do monitor do Salão;
6. identidade nativa do monitor como principal/não principal, para tolerar diferenças Qt/Win32 em setups mixed-DPI.

## Proteção

Com a automação ativa, a janela secundária é tratada como recurso gerenciado:

- se for minimizada, restaurar sem ativar deliberadamente a janela;
- se estiver no monitor correto, não reposicionar desnecessariamente;
- se estiver claramente no monitor errado, reposicionar com `SWP_NOACTIVATE`;
- nunca bloquear teclado/mouse do operador.

## Detecção de mídia

O detector lê somente uma região central da janela secundária identificada. A janela principal do JW Library não participa do sinal.

O estado de repouso (Texto do Ano + logo JW) é salvo como uma pequena assinatura visual persistente. Assim, ao ativar a automação:

- assinatura próxima do repouso → `Palco`;
- assinatura distante do repouso → `Mídias`.

Isso permite reabrir o Meeting Assistant durante uma mídia sem primeiro exibir `Palco`.

## Caminhos descartados como primários

- screenshot de fonte OBS inativa como sensor;
- observar várias janelas do JW Library ao mesmo tempo;
- captura do monitor inteiro como fonte de decisão;
- `HallOutputWindow` própria sobre a saída do JW Library;
- bloqueio de input, cliques visuais ou offsets de tela.

Esses caminhos podem continuar existindo apenas como diagnóstico/fallback experimental, não como núcleo da automação.

## Referências de arquitetura estudadas

- `viaart/DisplayedAppSwitcher` — identificação e gerenciamento das janelas secundárias JW Library/Zoom;
- `AntonyCorbett/JwlMediaWin` — reconhecimento estrutural da janela de mídia e proteção sem modificar o JW Library;
- `vicentegaete5/JWMediaFix` — cache de identidade, monitor escolhido e recuperação da janela;
- `sircharlo/meeting-media-manager` — separação clara entre estado de mídia, apresentação e eventos OBS;
- `mvpapen/JWL-Assistant` — OCR/ROI como alternativa de fallback, não detector principal.
