# Reaproveitamento técnico — pesquisa em 21/09/2026

Avaliação direcionada às pendências atuais. Nenhum código externo foi incorporado nesta revisão. As escolhas abaixo são recomendações; cada integração precisa de validação e revisão da licença da versão utilizada.

| Projeto/fonte | Aproveitamento concreto | Decisão |
| --- | --- | --- |
| [OBS WebSocket](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md) | Listar/criar cenas e fontes, alterar imagem e consultar/iniciar câmera virtual | Usar API existente em vez de automação por cliques |
| [obsws-python](https://github.com/aatikturk/obsws-python) | Cliente Python do protocolo v5 já presente no projeto | Reutilizar dependência; não criar outro cliente |
| [Python MSS](https://python-mss.readthedocs.io/stable/) | Captura de regiões de monitores; já presente no projeto | Usar para PNG da região JWL, com verificação de janela e prévia |
| [PyInstaller](https://pyinstaller.org/en/stable/operating-mode.html) | Empacota interpretador e bibliotecas | Candidato principal ao executável Windows; build e teste no Windows |
| [Hooks PyInstaller](https://github.com/pyinstaller/pyinstaller-hooks-contrib) | Integrações de empacotamento para dependências | Aproveitar hooks disponíveis; validar PySide6, plugins Qt, recursos e Win32/COM no executável |
| [Inno Setup](https://jrsoftware.org/isinfo.php) | Instalador Windows com atalhos, desinstalação e suporte a downloads/verificação | Candidato à camada de instalação sobre o executável |
| [M³](https://github.com/sircharlo/meeting-media-manager) / [guia](https://sircharlo.github.io/meeting-media-manager/) | Organização de mídia, configuração por congregação e documentação para operadores | Referência de produto/fluxos; não substituir o player JWL nesta etapa |
| [Advanced Scene Switcher](https://github.com/WarmUpTill/SceneSwitcher) | Automação OBS por regras e macros | Referência para testes/fluxos; não introduzir segundo controlador das mesmas cenas |
| [JwlMediaWin](https://github.com/AntonyCorbett/JwlMediaWin) | Tratamento da janela secundária JWL por UI Automation | Referência histórica; não substituir nem executar outro guardião sobre o núcleo congelado |

## OBS: limite entre reaproveitar e implementar

O protocolo oferece consultas/criação de cenas, criação/alteração de entradas e controle da câmera virtual. Ainda precisamos implementar a política do Meeting Assistant: detectar faltantes, tratar conflitos, mapear hardware local e confirmar resultado. A existência de uma cena não prova que sua fonte funciona.

Para a foto, usar captura direta da região JWL evita fotografar acidentalmente a cena Palco do OBS. A API de screenshot de fontes também existe, mas depende de selecionar a fonte certa. Manter foto de apresentação separada da referência do detector.

## Licenças e publicação

Os repositórios consultados indicam GPL-3.0 para obsws-python, AGPL-3.0 para M³ e GPL-2.0 para Advanced Scene Switcher. A dependência atual obsws-python já exige atenção à distribuição. Antes da Release, revisar licenças exatas, avisos e compatibilidade do conjunto; não escolher uma licença do app presumindo que todas as dependências são permissivas.

Inspiração de fluxo não exige copiar implementação. Se houver incorporação de código, registrar origem, versão/commit, licença e atribuição. A pesquisa não autoriza copiar trechos sob licença incompatível nem mudar a visibilidade do repositório.

## Instalação sem Python

PyInstaller inclui interpretador e dependências no pacote; o usuário não precisa instalar Python ou pip. Inno Setup pode instalar esse pacote e gerenciar dependências externas. O build não é universal: gerar Windows no Windows e validar em máquina limpa.

Separar três camadas: app empacotado; aplicativos externos OBS/Zoom/JWL; driver de áudio quando necessário. Downloads, licenças, privilégio/reinício e caminhos de instalação devem ser avaliados por componente. Evitar prometer automação universal da Store ou redistribuir drivers sem verificar os termos.

## O que não adotar agora

Um segundo motor de troca de cenas/janelas ou outro player aumentaria o risco de conflito com a versão aprovada. O maior ganho imediato vem de usar as APIs e bibliotecas já disponíveis para configuração, captura e empacotamento.
