# Microfone do operador no Zoom — correção de 03/10/2026

Entrega para execução pelo Python, a partir de `e9d4597`. Sem mudança de versão,
compilação nativa, instalador ou release. A validação física do novo controle ainda
depende de testar o Zoom instalado no PC do operador.

## Falhas reproduzidas

- Com `Mic Zoom ?`, o clique antigo apenas consultava o estado; não ativava o mic.
- Um estado anterior ainda considerado recente podia selecionar a ação errada.
- Uma consulta em andamento descartava silenciosamente o clique do operador.
- A busca exigia uma única classe antiga de janela e somente o texto do botão.
  As expressões amplas podiam interpretar `Ativar vídeo` como controle de áudio.

## Comportamento atual

Cada clique solicita alternar **seu próprio microfone**. O worker lê seu estado
atual, decide entre abrir/silenciar, envia uma única ação e verifica o resultado.
Enquanto a ação está pendente, o botão fica desabilitado. Uma consulta em segundo
plano pode adiar um clique, mas não descartá-lo. Estado ausente ou identificação
ambígua gera uma mensagem visível, sem comando enviado por tentativa.

`zoom_audio_controls.py` identifica o processo Zoom e o papel do controle próprio:
nome pessoal/atalho de áudio ou barra da reunião, excluindo linhas de participantes
e ações coletivas. Lê Name, HelpText, ItemStatus e propriedades LegacyIAccessible,
incluindo DefaultAction. O rótulo `Áudio` isolado não comprova aberto/mudo.

`zoom_audio.py` serializa consultas/comandos, inicializa COM MTA no worker,
verifica/cancela operações e informa falhas. Usa Invoke quando disponível ou a
ação LegacyIAccessible quando esse padrão estiver ausente **antes do envio**.
Não tenta uma segunda ação após um envio cujo resultado seja incerto.

A interface recebe resultados em slots Qt na thread principal. Ao sair, o serviço
cancela ações pendentes e suprime notificações tardias para objetos Qt já destruídos.
Essa condição foi reproduzida e coberta por uma regressão de encerramento.

Referências da implementação:
[threading UI Automation](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-threading),
[LegacyIAccessible](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-implementinglegacyiaccessible),
[pywinauto 0.6.9](https://pypi.org/project/pywinauto/0.6.9/).

## Atualização e teste no Windows 11

Feche o Meeting Assistant. Na pasta do projeto:

```powershell
git pull --ff-only
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

1. Entre em uma reunião de teste no Zoom e deixe visível a barra inferior.
2. Deixe seu microfone silenciado no Zoom. Clique **Mic Zoom** no app. Confira
   o ícone no Zoom: deve abrir; o app passa a oferecer **Silenciar Zoom**.
3. Clique novamente. O Zoom deve silenciar; o app oferece **Ativar mic Zoom**.
4. Mude o estado diretamente no Zoom e clique logo em seguida no app. O clique
   deve alternar o estado real, mesmo antes da próxima consulta periódica.
5. Repita com o Zoom minimizado. Se ele não expuser o controle nessa condição,
   o app deve informar a falha, liberar o botão e permitir tentar com a janela aberta.

Esses testes não exigem a segunda tela. Confira também que microfones dos demais
participantes permanecem como estavam. Não se declara sucesso pela simples
solicitação de uma ação ou pelos testes automatizados.

## Diagnóstico

A mensagem abaixo da prévia e o tooltip do botão informam o motivo da falha.
Com a telemetria já habilitada, `zoom_microphone` registra ação, estado observado,
alvo, tentativa/retorno do envio, confirmação, classes de janela, contagens e código
de erro. Consultas iguais não geram eventos repetidos. Não registra títulos de
reunião, nomes de participantes, rótulos brutos, credenciais ou atalhos digitados.

Se não funcionar, informe o horário do clique e a mensagem completa. Códigos como
`state_unavailable`, `control_not_found`, `ambiguous_control` e `not_confirmed`
distinguem falta de informação acessível de uma ação sem confirmação.

Os testes incluem cliques Qt reais com worker do serviço, estado desconhecido/
desatualizado, consulta ocupada, acessibilidade UIA/legacy simulada, participantes,
falhas parciais, cancelamento, COM e diagnóstico. Eles não substituem o ensaio do
Zoom real; fontes OBS, áudio, vídeo nativo e troca JWL/Zoom não foram alterados.
