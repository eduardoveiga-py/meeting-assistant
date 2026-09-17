# Validação física — motor da segunda janela do JW Library

Este roteiro existe para evitar probes longos e múltiplas rodadas de tentativa e erro.

## Pré-condições

- OBS aberto e WebSocket conectado.
- JW Library aberto com a segunda tela ativa no monitor do Salão.
- Na primeira execução deste motor, deixe o Texto do Ano + logo JW visível antes de ativar a automação.

## Uma única sessão de validação

1. Ativar automação com o Texto do Ano visível.
   - primeira execução: referência de repouso é salva;
   - OBS deve ir/manter `Palco`.
2. Tocar uma foto ou vídeo no JW Library.
   - OBS deve fazer fade para `Mídias`.
3. Encerrar a mídia até o Texto do Ano reaparecer.
   - OBS deve fazer fade para `Palco`.
4. Com automação ativa, minimizar a saída secundária do JW Library.
   - ela deve ser restaurada sem bloquear teclado/mouse.
5. Iniciar outra mídia, confirmar `Mídias`, fechar o Meeting Assistant e abri-lo novamente.
   - ao reativar a automação enquanto a mídia ainda estiver na Tela do Salão, deve ir/manter `Mídias` diretamente;
   - não deve ocorrer flash de `Palco` antes da classificação.

## Dados úteis em caso de falha

Uma única captura da janela do Meeting Assistant, da saída do Salão e do OBS deve ser suficiente. A linha `Sensor:` informa se o problema está na identificação/captura ou no comando de cena.
