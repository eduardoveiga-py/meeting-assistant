# Arquitetura Mestra — Meeting Assistant

Este documento descreve o fluxo **completo e absoluto** da operação, unindo a infraestrutura do Windows, o roteamento de áudio, o fluxo de vídeo nativo e a lógica interna do aplicativo *Meeting Assistant*.

---

## 1. Topologia Geral (Como o App controla o ecossistema)

O *Meeting Assistant* atua como o maestro, conversando com os outros softwares através de pontes invisíveis (WebSockets, UI Automation, APIs Nativas do Windows 11).

```mermaid
flowchart TD
    App{"🖥️ Meeting Assistant (Cérebro)"}
    
    subgraph Motores de Captura
        OBS["🎬 OBS Studio"]
        JWL["📖 JW Library"]
    end
    
    subgraph Destinos de Transmissão
        Zoom["🔵 Zoom"]
        Wapp["🟢 WhatsApp"]
    end
    
    %% Conexões do App
    App -- "obs-websocket (Cenas/Áudio)" --> OBS
    App -- "pywinauto/UIA (Lê Tela, Pausa/Muta)" --> JWL
    App -- "API Windows (Posição, Foco)" --> Zoom
    
    %% Fluxos Visuais
    JWL -. "Captura de Janela" .-> OBS
    OBS -. "Bridge DLL (Vídeo)" .-> Wapp & Zoom
```

---

## 2. A Lógica do App: Botões, Estados e Automação

O aplicativo não apenas clica em botões; ele gerencia "Estados" (Background, Speaker, Media, Zoom).

```mermaid
flowchart LR
    subgraph Botões do App
        B1("Fundo / Palco / Mídia")
        B2("Zoom ➔ Salão")
        B3("Ativar/Pausar Automação")
        B4("Cena Segura ➔ Palco")
    end

    subgraph Ações / Backend
        S1["Força cena no OBS"]
        S2["Traz Zoom pra Frente / Esconde JWL"]
        S3["Liga/Desliga Sensor Visual JWL"]
        S4["Pausa Automação + Corta pra Palco"]
    end

    subgraph Efeitos no Salão
        E1(("Muda Telão/Transmissão"))
        E2(("Mostra Participante na TV"))
        E3(("Vídeo roda automático"))
        E4(("Salva o operador do Pânico"))
    end

    B1 --> S1 --> E1
    B2 --> S2 --> E2
    B3 --> S3 --> E3
    B4 --> S4 --> E4
    
    %% Relações Especiais
    B2 -. "Força pausa na" .-> B3
    S3 -. "Monitora repouso do JWL" .-> S1
```

### Funções Vitais do App:
*   **Guardião de Janela (JWL Fast Window Guard):** Fica em loop (180ms) garantindo que o JW Library esteja na tela secundária, na posição correta, sem barras do Windows por cima.
*   **Ducking Inteligente:** Abaixa o áudio da música de fundo automaticamente quando começa a reunião ou quando um vídeo é tocado.
*   **Controle de Microfone do Zoom:** Injeta cliques UIA diretamente no botão "Mute" do Zoom, com tempo de resposta ultrarrápido, sem precisar que o operador foque na janela do Zoom.

---

## 3. Estrutura do OBS: Cenas, Fontes e Filtros

O app exige uma estrutura rigorosa no OBS para poder rotear tudo com segurança.

```mermaid
mindmap
  root((OBS Studio))
    Cenas
      Fundo
        (Imagem: Texto do Ano)
      Palco
        (Vídeo: Câmera Física)
        (Áudio: Mesa de Som)
      Mídias
        (Vídeo: Captura JW Library)
        (Áudio: JWL Application Audio)
    Filtros de Áudio
      Mesa de Som
        1. Limitador (Impede estouro)
        2. Ganho (Controlado pelo App)
      JWL Áudio
        1. Limitador
        2. Audio Monitor (Envia pro WhatsApp)
```

---

## 4. O Fluxo de Vídeo Definitivo (Câmeras Virtuais)

O projeto usa **duas** vias de vídeo para contornar restrições do Windows 11 e do WhatsApp.

```mermaid
flowchart LR
    Cam["Câmera Física"] --> OBS
    JWL["JWL (Mídia)"] --> OBS
    OBS -- "Sinal Program (Misturado)" --> Bridge
    
    subgraph A Mágica do Meeting Assistant
        Bridge["meeting-assistant-bridge.dll"]
        Win11["Win11 Media Foundation"]
        Bridge -- "Injeta NV12 720p30" --> Win11
    end
    
    Win11 -- "Câmera Virtual Nativa" --> WhatsApp["WhatsApp Desktop"]
    Win11 -- "Câmera Virtual Nativa" --> Zoom["Zoom"]
    
    %% Fallback
    OBS -. "OBS Virtual Camera Tradicional" .-> Zoom
```
*Por que a Bridge DLL?* O WhatsApp UWP do Windows 11 frequentemente recusa a "OBS Virtual Camera" padrão. O nosso projeto cria uma câmera nativa a nível de núcleo (Media Foundation) que engana o WhatsApp perfeitamente.

---

## 5. Roteamento de Áudio: Com e Sem WhatsApp

Aqui está o coração do "Mix-Minus", separando o perfil básico do perfil avançado.

### Cenário A: Sem WhatsApp (Apenas Zoom) - 1 Cabo Virtual
```mermaid
flowchart LR
    Mesa["🎤 Mesa de Som"] --> OBS
    JWL["▶️ JWL Mídias"] --> OBS
    OBS -- "Dispositivo de Monitoramento" --> CaboA["VB-Cable A"]
    CaboA -->|"Input"| ZoomMic["🎙️ Zoom Microfone"]
    ZoomFalante["🔊 Zoom Alto-falante"] --> Retorno["Caixa do Salão"]
```

### Cenário B: Com WhatsApp (Dual Cable + Audio Monitor Plugin)
Neste cenário, o WhatsApp precisa ouvir o Salão, mas não pode ouvir a si mesmo nem o Zoom.

```mermaid
flowchart TD
    Mesa["🎤 Mesa de Som"] --> OBS["OBS Studio"]
    JWL["▶️ JWL Mídias"] --> OBS
    
    %% Rota Zoom (Padrão)
    OBS -- "Áudio de Monitoramento Global" --> CaboA["VB-Cable A"]
    CaboA --> ZoomMic["🎙️ Zoom Mic"]
    
    %% Rota WhatsApp (Exclusiva via Plugin)
    OBS -- "Filtro: Audio Monitor (Plugin)" --> CaboB["VB-Cable B"]
    CaboB --> WappMic["🎙️ WhatsApp Mic"]
    
    %% Saída Física Segura
    ZoomSpk["🔊 Zoom Áudio"] --> SaidaFisica["Caixas do Salão"]
    WappSpk["🔊 WhatsApp Áudio"] --> SaidaFisica
```
*O Pulo do Gato:* Como a saída do Zoom vai direto para a caixa do Salão e não volta pro OBS, o WhatsApp não capta o eco do Zoom. Cada um tem seu microfone alimentado por um cabo virtual dedicado.

---

## 6. O Fluxo de Emergência (Troubleshooting do App)

O que o app faz quando algo dá errado:
1. **JWL minimizou ou perdeu foco?** O `JWLFastWindowGuard` detecta em menos de 1 segundo, tira o estado de *cloak* (oculto do Windows), desminimiza, restaura as coordenadas e traz para o monitor secundário.
2. **OBS perdeu conexão WebSocket?** O `obs_controller.py` tenta reconectar em loop sem travar a interface Qt, avisando na barra inferior.
3. **Mídia tocou, mas cena não mudou?** O operador clica no botão "Mídia" manualmente. Se precisar cancelar tudo, aperta **"Cena Segura -> Palco"**, o que força a câmera do salão e pausa a automação instantaneamente até o operador resolver o problema.
