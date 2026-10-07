# Ajustes, fontes OBS e volumes

Organização implementada em 07/10/2026 para execução por Git/Python. **Ajustes**
reúne configuração e manutenção; **Volumes**, no painel principal, abre a mesma
janela diretamente nos controles de nível. Não há uma segunda cópia dos dados.

**Aceite da organização:** em 07/10/2026, após atualizar para `7a7697a`, o
operador respondeu: “Os ajustes ficaram ótimo!”. Isso confirma a organização
relatada da interface. Instalação real de plugins, repetição da preparação OBS
e escuta de todos os perfis continuam tendo critérios próprios; não foram
declarados aprovados por esse retorno. Volumes e Ajustes recebem ícones SVG
com os rótulos preservados, na mesma célula do painel.

## Onde encontrar cada opção

| Categoria | Conteúdo | Quando usar |
| --- | --- | --- |
| Reunião e janelas | Tela do Salão, aplicativos, link Zoom, atalhos e disposição | Configuração inicial ou mudança de equipamento |
| OBS e vídeo → Conexão | WebSocket, mapeamento de cenas e câmera IP do Palco | Conectar OBS ou alterar a câmera |
| OBS e vídeo → Fontes | Verificação/conclusão das fontes, captura JWL e câmera virtual OBS | Instalação e manutenção |
| OBS e vídeo → Texto do Ano | Capturar, conferir, salvar e aplicar a foto | Primeira foto ou atualização anual |
| OBS e vídeo → WhatsApp | Câmera nativa, prévia compartilhada e diagnóstico | Conferir o vídeo |
| Áudio → Volumes | Ganhos por fonte | Operação cotidiana |
| Áudio → Envio | Mesa, aplicativos, perfil/cabos, filtros e sincronização | Preparar ou mudar o roteamento |
| Áudio → Ajuda | Ligações e conferência do áudio | Consultar instruções |
| Instalação e plugins | Verificação do ambiente e instalação explícita | Primeiro uso ou dependência ausente |
| Diagnóstico | Telemetria, calibração, observação e histórico de versões | Investigar ou recuperar a configuração |

A navegação fica em uma janela, com área rolável por categoria e rodapé acessível.
Campos gerais usam **Salvar ajustes**. Áudio, volumes, foto e instalação têm ações
próprias, com confirmação do resultado. Fechar com edições gerais pendentes oferece
salvar, descartar ou cancelar. Seleções de áudio e foto não salva também geram aviso.

## Completar o OBS sem refazer o que funciona

Faça manutenção fora da reunião, com automação pausada, Zoom → Salão e mídia externa
encerrados. Abra OBS/JWL e confira o monitor e o WebSocket.

1. Em **OBS e vídeo → Fontes**, clique **Verificar fontes e plugins**. O relatório separa
   itens existentes, ausentes e pendências. A consulta não altera o OBS.
2. Resolva pré-requisitos: plugin ausente, foto não salva ou dados da câmera IP.
   Plugins ficam em **Instalação e plugins**, com OBS fechado.
3. Clique **Completar fontes ausentes**. O app usa os nomes de cenas já mapeados,
   cria apenas cenas/fontes/vínculos ausentes e consulta o resultado novamente.
4. Confira a imagem das fontes no OBS. Repetir a conclusão não deve criar cópias
   nem interromper o áudio existente.

Fontes pessoais, RTSP existente, filtros, ganhos e roteamento são preservados.
Fontes de áudio novas começam desativadas e silenciadas. Seleção dos dispositivos
e **Ativar envio** continuam explícitos na categoria Áudio. A conclusão não troca
Program nem renomeia cenas.

Nome reservado ocupado por outro tipo, vínculos duplicados ou fontes desativadas
pelo operador aparecem para revisão; não são apagados ou reativados silenciosamente.
Para alterações intencionais, use **Aplicar câmera IP em Palco**, **Aplicar foto
salva no OBS** ou **Preparar captura JWL**, conforme o caso. A migração JWL só
desativa a captura antiga após confirmar a nova fonte por HWND.

Estrutura de áudio não certifica o mix. Dispositivos, filtros, cabos e escuta remota
são conferidos em **Áudio → Envio**. Uma URL IP presente não comprova imagem recebida.

## Plugins e instalação no desenvolvimento

Em **Instalação e plugins**, marque a autorização da operação escolhida.
O app exige OBS fechado antes de instalar componentes nele.

- **Captura JWL:** reutiliza o instalador existente, com versão/hashes fixados;
  baixa a DLL pronta quando necessário.
- **Câmera e ponte OBS:** reutiliza os componentes prontos do mecanismo existente,
  sem recompilar nem atualizar à força uma câmera já instalada.
- **Audio Monitor:** baixa o ZIP oficial 0.10.1 do Exeldro, verifica SHA-256 e
  instala somente DLL x64/traduções. Arquivos diferentes recebem backup;
  arquivos idênticos não são substituídos. Reabra OBS e verifique fontes.
- **Aplicativos e VB-CABLE:** usam os fluxos oficiais existentes. Store, drivers,
  elevação e reinício podem exigir interação. Audio Monitor não instala outro cabo.

Download/verificação/instalação rodam fora da thread da interface. Esta
reorganização não altera binários nativos nem gera release ou instalador.

## Volume para o operador

1. Clique **Volumes** no painel principal.
2. Altere o ganho desejado e clique **Aplicar volumes**.
3. Ouça no outro dispositivo. Comece em 0 dB e use passos pequenos; é possível
   reduzir até −30 dB ou aumentar até +18 dB. O limitador contém picos, mas não
   recupera uma entrada já distorcida.

Aplicar somente ganho preserva mute, monitoramento, dispositivos, faixas e rota.
As alterações são confirmadas por leitura no OBS e só então persistidas. Em falha,
o serviço tenta restaurar valores anteriores e informa restauração incompleta.
Fontes sem ganho/limitador prontos pedem configuração em Envio.

Filtros de ruído/compressão e atraso ficam recolhidos em **Envio → Filtros e
sincronização**. O atraso usa o intervalo OBS (−950 a 20.000 ms). Se também foi
editado, **Aplicar volumes** confirma essa edição junto dos níveis; sem edição
de atraso, escreve somente os ganhos alterados.

## Roteiro de aceite

- Abrir categorias, conferir monitores/cenas/cabos/foto e reabrir. Salvar uma
  alteração geral e verificar que os demais dados persistem.
- Ajustar uma fonte em poucos dB e confirmar no OBS/recepção remota. Não deve
  interromper o áudio nem alterar o volume das caixas do Salão.
- Verificar/completar duas vezes uma coleção de teste: sem cópias, troca de
  Program ou mudança no envio existente. Não apague fontes reais só para testar.
- Conferir layout na escala/resolução do computador; repetir JWL/Zoom, mídia e
  Windows+D conforme o [contrato validado](validated-hall-contract.md).

Testes automatizados cobrem cliques Qt, salvamento, falhas parciais, preparação
idempotente, instalação sem compilador e layout em 100%, 125%, 150% e 200%.
Eles não substituem instalação real, dois monitores ou escuta física das chamadas.
