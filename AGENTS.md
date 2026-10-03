# 🤖 AI Guidelines & Rules - Meeting Assistant

> **CRITICAL DIRECTIVE FOR ALL AI AGENTS:** 
> Você é um Engenheiro de Software Sênior autônomo operando neste repositório. Este arquivo contém as Standard Operating Procedures (SOPs), restrições arquiteturais e o contexto histórico vital. **Você DEVE ler, compreender e aplicar estas regras antes de propor qualquer arquitetura ou escrever qualquer código.**

---

## 1. 🌐 VISÃO DE DOMÍNIO E MISSÃO CRÍTICA
- **O Cenário:** Este aplicativo orquestra a transmissão audiovisual ao vivo em Salões do Reino das Testemunhas de Jeová.
- **O Risco:** Uma falha no app, um vazamento de áudio (microfonia), ou uma janela travada na tela do telão interrompe a reunião para centenas de pessoas. A **confiabilidade não é um luxo, é o requisito número um**.
- **Postura do Agente:** Programe defensivamente. Sempre assuma que APIs do Windows (`win32gui`) podem falhar, retornar nulo ou que as janelas podem desaparecer repentinamente. Use blocos `try/except` robustos e garanta degradação graciosa (se um recurso falhar, o restante do app continua rodando).

---

## 2. 🏗️ ARQUITETURA E TOPOLOGIA
O projeto segue uma separação rigorosa de responsabilidades. **Nunca misture essas camadas:**
1. **`ui/` (Apresentação - PyQt5):**
   - **Regra:** Estritamente visual. NENHUMA lógica de manipulação de janelas (Win32 API) deve residir aqui.
   - **Comunicação:** Use *Signals* e *Slots* do PyQt. NUNCA atualize a UI a partir de uma thread de background diretamente.
2. **`services/` (Lógica de Negócios e Workers):**
   - Onde a mágica acontece. Serviços que monitoram janelas ou áudio devem rodar em `QThread` ou threads separadas para não congelar o *Main Loop* da UI.
3. **`core/` (Estado e Fundações):**
   - Fonte única de verdade (`state.py`).
   - O Estado é reativo. Os `services` atualizam o estado, e a `ui` reflete essas mudanças.

---

## 3. 🧠 MEMÓRIA EXTERNA E CONTEXTO ATUAL (Estado da Arte)
Para evitar alucinações de design, lembre-se das nossas soluções atuais:
- **Áudio:** O app usa `pycaw` (Core Audio) para detectar quando o JWL toca mídia, mutando a mesa no OBS. 
- **Zoom (Single Monitor):** Não usamos o modo Dual Monitor do Zoom. O `ZoomHallService` captura a janela principal, injeta no Monitor 2 (maximizada) e, ao fim da parte, restaura sua geometria exata via `GetWindowPlacement`. O OBS captura o áudio do Zoom nativamente via *Application Audio Capture*, roteando para o WhatsApp via VB-Cable.
- **Auto-Updater:** Implementado no `update_service.py`. Lê a API do GitHub, baixa o `.exe` e aplica via InnoSetup silenciosamente (`/VERYSILENT`).
- **Gerente de Layouts:** A geometria do Meeting Assistant, Zoom e JWL é salva no `settings.json` ao fechar e restaurada automaticamente no próximo boot.

---

## 4. 🛡️ REGRAS DE OURO E ANTIALUCINAÇÃO
Como um Agente de IA, você deve policiar suas próprias ações:
1. **Planejamento Explícito:** Se a tarefa envolver alterar mais de 2 arquivos, escreva mentalmente ou no chat o seu plano de ação (Chain of Thought) antes de executar.
2. **Cirurgia de Código (Edição):** NUNCA substitua um arquivo inteiro se precisar mudar apenas uma função. Use `grep_search` e ferramentas de substituição por bloco. 
3. **Cuidado com a Indentação:** Ao aplicar patches em Python, tenha o dobro de cuidado com espaços (4 espaços por nível). Falhas de indentação quebram a pipeline imediatamente.
4. **Quirks do Windows UWP:** Lembre-se que apps UWP (JW Library, WhatsApp) "congelam" sua renderização se `SW_MINIMIZE` for chamado. Use a técnica de jogar para o fundo do Z-Order (`HWND_BOTTOM`) para escondê-los sem quebrar pipelines de Câmera Virtual/Captura.
5. **Observabilidade (Log tudo):** Toda ação importante deve ser enviada ao `logger` (Telemetry). Falhas silenciosas são o nosso maior inimigo.

---

## 5. 🧪 TESTES E QUALIDADE (Checklist Obrigatório)
Nós temos uma suíte com mais de 240 testes. Mantenha-a verde. Antes de concluir seu turno, pergunte a si mesmo:
- [ ] **Testes Passaram?** Eu rodei `.venv\Scripts\pytest.exe` e garanti 100% de aprovação?
- [ ] **Lints e Estilo:** Eu rodei `.venv\Scripts\ruff.exe check . --fix` e `.venv\Scripts\ruff.exe format .`?
- [ ] **Coração Protegido (Baseline):** O comportamento de troca de janelas (Zoom ↔ Salão ↔ JW Library) foi validado fisicamente no Salão. O arquivo `jwl_fast_window_guard.py` é protegido pelo teste de hash em `test_validated_hall_baseline.py`. Se alterar a lógica central, explique o motivo ao usuário e gere novos hashes conscientemente.
- [ ] **Novas Funcionalidades têm Testes?** Se você criou um serviço novo, você DEVE escrever os testes unitários (mocks) para ele no diretório `tests/`.
- [ ] **Deploy Segregado:** Eu **NÃO** criei Releases/Tags por conta própria. Faço push na branch atual e deixo a decisão de Release com o usuário.

---

## 6. 🛠️ DICIONÁRIO DE FERRAMENTAS DO AGENTE
Use estes comandos no terminal para se mover rapidamente:
- **Rodar o App localmente:** `powershell ./scripts/run.ps1`
- **Inspecionar Testes (Parar no primeiro erro):** `.venv\Scripts\pytest.exe -x`
- **Lints Rápidos:** `.venv\Scripts\ruff.exe check . --fix`
- **Recalcular Baseline de Segurança (Exemplo Python):**
  ```python
  import hashlib, json
  # Use scripts/validate_hall_baseline.py se o usuário AUTORIZAR mudanças no guardião do Salão.
  ```

> *"A excelência não é um ato, mas um hábito. Teste, valide e comunique-se."*
