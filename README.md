# Meeting Assistant 3.0

Assistente de operação para reuniões usando **OBS Studio, Zoom e JW Library** em Windows.

## Estado atual

A versão 3.0 está sendo reconstruída sobre uma arquitetura modular. O primeiro marco contém a interface PySide6, modelo de estado centralizado, configurações persistentes, testes e CI para Windows. As integrações reais com OBS, JW Library e Zoom serão adicionadas separadamente para reduzir regressões.

## Requisitos de desenvolvimento

- Windows 10/11 x64
- Python 3.12 x64
- Git for Windows

## Preparar o ambiente

No PowerShell, dentro da pasta do projeto:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

## Executar

```powershell
meeting-assistant
```

Alternativamente:

```powershell
python -m meeting_assistant.main
```

## Testes e qualidade

```powershell
ruff check .
pytest
```

## Arquitetura

```text
src/meeting_assistant/
├── core/       # estado e coordenação da operação
├── services/   # configuração, diagnóstico, logging, preview
├── controllers/# OBS, Windows, JW Library, Zoom e monitores
└── ui/         # interface PySide6
```

Princípios do projeto:

- Win32/pywin32 para manipulação confiável de janelas no Windows.
- OBS WebSocket para controle do OBS.
- Sem reconhecimento de imagem/cliques cegos em fluxos essenciais.
- Estado operacional centralizado em vez de regras espalhadas pela UI.
- Automação inicia pausada e deve possuir retorno visual e uma saída segura.
- Testes automatizados antes de integrar automações físicas.

## Desenvolvimento

O desenvolvimento é feito em branches e Pull Requests. O CI é executado em Windows com Python 3.12, Ruff e Pytest.
