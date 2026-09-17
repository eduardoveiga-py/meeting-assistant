# Projetos de referência

O Meeting Assistant usa ideias arquiteturais estudadas nestes projetos, sem importar a arquitetura inteira de nenhum deles.

## viaart/DisplayedAppSwitcher — MIT

Conceitos adotados:
- distinguir a segunda janela do JW Library da principal;
- reconhecer o título especial `Second Display ‎- JW Library`;
- usar fullscreen/ausência de title bar como sinais de segunda tela;
- tratar JW Library e Zoom como aplicações que disputam uma saída secundária.

## AntonyCorbett/JwlMediaWin

Conceitos adotados:
- não confiar somente no processo host;
- validar estruturalmente a janela do JWL por `Windows.UI.Core.CoreWindow`;
- cachear/redescobrir a janela quando necessário;
- proteger a janela sem modificar o código do JW Library.

## vicentegaete5/JWMediaFix — MIT

Conceitos adotados:
- monitor escolhido de forma persistente;
- recuperação de janela minimizada/deslocada;
- reavaliação quando a topologia dos monitores muda.

## sircharlo/meeting-media-manager — AGPL

Conceitos adotados:
- separar estado de mídia, apresentação e automação OBS;
- eventos determinísticos de mídia são preferíveis a inferências por uma fonte OBS inativa;
- saída do Salão e saída para Zoom são conceitos diferentes.

Como o Meeting Assistant mantém o JW Library como player, não reutiliza o modelo do M³ de possuir o próprio player como fluxo principal.

## mvpapen/JWL-Assistant

Conceitos avaliados:
- OCR/ROI pode funcionar como fallback visual;
- integração JWL + OBS + Zoom confirma a utilidade de automação orientada ao estado da mídia.

OCR não é o detector primário do Meeting Assistant porque depende mais de escala, texto e configuração de ROI.
