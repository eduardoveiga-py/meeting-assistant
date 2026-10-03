# Orientações de manutenção — Meeting Assistant
Este arquivo orienta agentes e colaboradores deste repositório. Instruções atuais
do operador prevalecem. Avance dentro do escopo solicitado, sem pedir novamente
aprovação para escolhas técnicas rotineiras ou ações já autorizadas. Confirme
mudanças que alterem o objetivo do app.

Estas regras não certificam a versão atual. Código presente, integração concluída,
testes automatizados e validação física são evidências distintas.

## 1. Objetivo e plataforma
- Operar reuniões com JW Library, OBS, Zoom e WhatsApp, preservando o som e a
  imagem do Salão. Confiabilidade durante a reunião tem prioridade.
- Windows 11 x64; câmera própria por Media Foundation. Não retome NDI ou as
  tentativas de compatibilidade com Windows 10 sem mudança explícita de objetivo.
- Interface: PySide6 / Qt 6. Desenvolvimento: Python 3.12 x64. Consulte
  pyproject.toml antes de modificar versões, framework ou dependências.
- O operador testa atualizando o código com Git e executando scripts/run.ps1.
  Executável e instalador são uma etapa separada.

## 2. Antes de alterar
1. Confira revisão, branch e alterações locais. Preserve trabalho existente;
   não descarte arquivos nem reescreva histórico para obter uma árvore limpa.
2. Leia instruções adicionais aplicáveis à tarefa. Consulte
   [README](README.md), [decisões](docs/decision-log.md),
   [pendências](docs/roadmap-after-hall-validation.md) e os contratos pertinentes.
3. Compare documentação com implementação: chamadas em main.py, conexões de
   sinais, configurações persistidas e testes. Uma classe existente não prova
   que a função está conectada à interface ou à inicialização.
4. Para mudanças que cruzem módulos, apresente um plano curto com ações e
   verificações. Não exponha raciocínio interno privado.
5. Faça patches proporcionais à tarefa. Não inclua formatação global, troca de
   framework ou refatoração do núcleo como efeito colateral.

Não invente caminhos, comandos, configurações ou resultados. Não trate histórico
de conversa indisponível como recuperado. Havendo divergência entre documentação
e código, registre-a antes de declarar uma funcionalidade concluída.

## 3. Responsabilidades e integração
Os caminhos abaixo são relativos a src/meeting_assistant/:
- `ui/`: Widgets, apresentação, sinais e interação do operador
- `services/`: Integrações OBS/Windows, áudio, janelas, vídeo e persistência
- `core/`: Estado e contratos compartilhados
- `main.py`: Composição dos serviços e conexões entre módulos

- Mantenha manipulação Win32 nos serviços. A UI solicita ações e exibe resultados;
  main.py conecta componentes sem duplicar sua lógica.
- Atualize widgets somente na thread da GUI, usando sinais/slots do Qt. Rede,
  captura, espera de processos e tarefas demoradas não podem bloquear a interface.
- Workers precisam de cancelamento, encerramento com prazo e liberação de recursos.
  Inicialize COM na thread que o utiliza quando necessário.
- Inicialização e reconexão devem ser idempotentes: evite serviços, leitores de
  vídeo, atalhos ou conexões de sinais duplicados.
- Trate erros nas fronteiras das integrações. Não esconda falhas com except: pass
  nem transforme uma solicitação enviada em mensagem de sucesso confirmado.

## 4. Contratos funcionais
Estes são requisitos de manutenção, inclusive quando o código atual os descumpre.
Não documente uma regressão como se fosse uma nova decisão autorizada.

### Janelas e automação
- O JWL é a saída padrão da segunda tela. O guardião começa com o app e funciona
  também quando a automação de mídia está pausada.
- Enquanto o operador solicita Zoom no Salão, o guardião respeita essa escolha.
  No retorno, restaure e confirme a visibilidade do JWL antes de retomar o sensor.
- A exibição local do Zoom não deve colocar seu retorno no Program enviado à
  chamada. O OBS permanece responsável por Program e suas transições.
- Texto do Ano em repouso corresponde a Palco; mídia real corresponde a Mídia e,
  ao terminar, retorna a Palco. A detecção existente usa o sensor visual do JWL e
  referência de repouso; não descreva pycaw como detector sem verificar o código.
- Identifique janelas por processo, classe e papel. Confira existência, posição,
  minimização, cloaking e exposição; título ou IsWindowVisible isolados não
  confirmam a janela efetivamente exibida no monitor.
- Preserve a reunião e as janelas ao alternar JWL/Zoom. Não feche a janela do Zoom
  para escondê-la. Salve sua geometria original uma vez por ciclo de projeção,
  sem sobrescrevê-la nas tentativas de recuperação.
- Minimizar pode afetar captura/renderização em alguns aplicativos. Não presuma
  que SW_MINIMIZE ou HWND_BOTTOM resolva todos os casos.
- Layouts distinguem janela principal/secundária, escala DPI, coordenadas físicas
  e lógicas, área útil e monitores desconectados. Atalhos são registrados uma vez
  e liberados ao sair; informe conflitos sem desativar atalhos globais do Windows.

O contrato histórico usa a janela secundária do Zoom. Mudanças para projetar ou
capturar a principal precisam ser documentadas e revalidadas, incluindo vários
participantes; não herdam automaticamente a validação histórica.

### Áudio e vídeo
- Consulte [o roteamento de áudio](docs/audio-routing.md), comparando o documento,
  o código e a instalação real. Capture mesa e mídias como fontes identificadas;
  evite captura genérica que recapture chamadas e produza duplicação ou microfonia.
- Mix-minus: o microfone enviado a uma chamada exclui o retorno dessa chamada.
  Um VB-CABLE pode servir aos dois aplicativos para o mesmo mix local; acrescentar
  retorno do Zoom para o WhatsApp exige um caminho separado do envio ao próprio Zoom.
- Verifique também o caminho físico da mesa. Software não separa com confiabilidade
  sinais já somados nessa entrada; não prometa resolver esse loop só com cancelamento
  de eco. Ganho no envio às chamadas deve preservar o som do Salão e evitar clipping.
- O retorno do WhatsApp começa silenciado. Seu controle afeta somente a reprodução
  do WhatsApp, preservando Zoom, mídias, microfones e volume geral.
- Preserve [o fluxo nativo de vídeo](docs/windows11-video-architecture.md): Program
  do OBS, bridge, fonte Media Foundation e câmera Windows 11. Reutilize o leitor de
  prévia e o renderizador Qt, com quadros recentes e filas limitadas; não acrescente
  captura JPEG periódica em paralelo para resolver fluidez.
- Câmera iniciada no Windows não comprova recepção fluida no WhatsApp. Distinga
  métricas de bridge, prévia, entrega ao cliente, CPU e recepção remota.

### Configuração e ciclo da reunião
- Configure cenas/fontes de forma idempotente, preservando fontes do operador.
  Detecte capturas antigas do monitor que possam reintroduzir espelhamento.
- Na foto do Texto do Ano, diferencie captura candidata, gravação persistida e
  aplicação no OBS. Confirme arquivo e fonte; não anuncie sucesso após falha parcial.
- Verifique operações pela conexão OBS configurada. Um endereço de rede pode
  pertencer ao próprio PC; loopback ou caminho padrão do OBS não são requisitos.
  OBS remoto exige acesso explícito ao arquivo da foto.
- Iniciar/encerrar reunião preserva configurações e coordena serviços/aplicativos.
  Solicite encerramento normal; não force todos os processos como padrão nem ignore
  diálogos de confirmação do anfitrião.

## 5. Núcleo validado e proteção contra regressões
- Contrato e roteiro físico: [validated-hall-contract.md](docs/validated-hall-contract.md).
- Manifesto: [validated-hall-baseline.json](docs/validated-hall-baseline.json).
- Teste: tests/test_validated_hall_baseline.py.
- Referência histórica: commit 02094d80aa45ab0088d271691122839da759b1ee e branch
  checkpoint/zoom-jwl-validated-20260921. Não mova nem sobrescreva esse checkpoint.

Mudanças nos arquivos protegidos ou nas conexões de ativação, pausa e retomada
precisam resolver uma solicitação concreta do operador, explicar o impacto e
incluir regressões pertinentes. Funcionalidades independentes usam interfaces existentes.

Não recalcule hashes apenas para passar o CI. Hash comprova integridade, não
comportamento. Antes de atualizar a referência validada, obtenha confirmação física
para a revisão candidata e registre revisão, ambiente, cenários e resultado,
preservando o checkpoint anterior. Se a validação não puder ser feita agora,
entregue a alteração como candidata com essa pendência explícita. Não atribua a
confirmação de uma versão antiga a código posteriormente alterado.

## 6. Verificações e evidência
- Rode testes relevantes e, para mudanças de comportamento ou integração, a suíte
  de regressão. Teste eventos/conexões da UI quando afetados; mocks de métodos
  isolados não comprovam que o botão funciona.
- Use Ruff primeiro sem correções automáticas. Limite formatação e correções aos
  arquivos necessários, respeitando a proteção do núcleo.
- Mudanças de distribuição exigem verificar também .spec, scripts PowerShell,
  workflows, versões, manifesto e conteúdo dos pacotes.
- Diferencie teste unitário, integração, compilação, instalação e ensaio físico.
  Testes em Linux ou sucesso do CI não comprovam dois monitores, áudio físico ou
  chamada real no Windows 11.
- Para janelas, siga o roteiro do contrato: ciclos repetidos com automação ligada
  e pausada, Windows+D, retorno imediato ao JWL, repouso/mídia e reinício do app.
  Confirme ausência de retorno indevido do Zoom no vídeo das chamadas.
- Informe resultados reais, avisos relevantes e verificações pendentes. Não fixe
  uma contagem de testes como característica permanente.

Comandos existentes, na raiz e com dependências de desenvolvimento instaladas:
```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest tests/test_validated_hall_baseline.py
.\.venv\Scripts\python.exe -m ruff check .
```

Para executar o código Python:
```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1
```
Essa opção vale para o processo iniciado; não altere a política global do Windows.
Verifique scripts antes de recomendá-los; não cite utilitários inexistentes.

## 7. Distribuição, diagnóstico e entrega
- Não exija compilação local para testar mudanças Python. Use o mecanismo existente
  para obter componentes nativos, verificando origem, versão e integridade. Uma DLL
  alterada exige binário correspondente; atualizar Python sozinho não a substitui.
- Respeite pedidos como "não compile agora". Antes de push, PR, tag ou disparo de
  workflow, confira gatilhos em .github/workflows/: publicar código pode acionar
  compilação automaticamente. Escolha uma entrega compatível com o pedido.
- Push, release e instalação seguem o escopo já autorizado. Não publique release,
  mude versão ou distribua binários por iniciativa própria durante uma revisão.
- Atualizador precisa estar conectado ao app, comparar versões, verificar
  integridade, preservar configurações e distinguir execução Python de instalação.
  Não substitua componentes durante uma reunião em andamento.
- Registre intenção, resultado, erro e recuperação, controlando frequência de
  eventos. Não registre senhas, credenciais, links privados ou dados de participantes;
  envio de diagnósticos respeita a configuração e autorização do operador.
- Sem acesso à telemetria da máquina, informe a limitação e forneça a coleta.
  Não substitua observação por suposição.
- Ao concluir, explique o que mudou, por quê, como foi verificado e o que depende
  de teste físico. Entregue passos curtos com resultado esperado.
- Atualize decisões, pendências e notas de release com evidências. Neste arquivo,
  mantenha regras estáveis; funções desconectadas ou não testadas continuam pendentes.
