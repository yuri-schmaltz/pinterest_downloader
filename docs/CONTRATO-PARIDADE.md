# Contrato de paridade v1

Estado: em implementação, 2026-11-06. A matriz `tests/fixtures/parity/requirements.json` é o inventário de aceite; “planned” não é comprovação.

## Entradas e semântica

- Usuário ou URL de perfil descobre quadros; URL `/usuario/quadro/` coleta um quadro. Caminhos de pin não são perfis.
- `max_pins` é por quadro e positivo. `workers` e `boards_workers` são positivos e limitam trabalhos reais em voo.
- `pins/<usuario>/<quadro>/` é o destino de compatibilidade Python planejado. O layout Rust atual `<usuario>_<quadro>` continua até haver migração explícita.
- O parâmetro `--no-cache` Rust existente ignora arquivos de mídia. Foi preservado. O cache de metadados tem controle próprio (`--no-metadata-cache`), separado até haver migração documentada.
- `--cache-dir` aponta o cache de metadados para um diretório específico. Sem a opção vale o diretório do sistema (XDG em Linux/macOS, `LOCALAPPDATA` no Windows). O arquivo é `.pinterest_cache.json` e tem o mesmo formato do Python, de modo que o mesmo diretório pode ser compartilhado.
- O cache de metadados é otimização, nunca fonte de verdade: um arquivo ausente, vazio ou corrompido é descartado em vez de derrubar a execução, e uma gravação falha emite aviso sem falhar a execução. Não há expiração nem versionamento ainda.
- Modo HTTP explícito produz snapshot de completude desconhecida. Modo automático não usa a presença de alguns pins como evidência de fim.
- Estabilidade de scroll não comprova completude. Somente um sinal inequívoco de fim no contexto do quadro permite `complete`. Um limite pedido produz `limited`.
- Erros de extração, login obrigatório e quadro vazio comprovado são resultados diferentes. Mensagens ambíguas não devem inferir privacidade ou inexistência.

## Eventos e execução

`RunEventEnvelope` versão 1 identifica operação, sequência, horário e quadro/pin. Os produtores não registram cookies ou headers de autenticação. A interface deve consumir o canal até o evento terminal ou fechamento. Progresso pode ser agregado/descartado sob pressão; eventos de controle e terminal têm entrega com backpressure. A task de apresentação precisa permanecer ativa enquanto o motor encerra.

`Operation` fornece cancelamento compartilhado. CLI/GUI devem cancelar e continuar drenando eventos até a operação terminar. Fechar a interface fecha o receptor e desbloqueia produtores. Uma única task de motor por operação estabelece a ordem dos eventos; helpers não devem emitir eventos concorrentes cuja ordem tenha significado transacional.

Resultados distinguem descobertos, resolvidos, baixados, reutilizados, verificados, falhos e ignorados. Totais não podem somar reuso como novos downloads. Estados terminais e códigos de saída serão estabilizados com o runner completo, mantendo o contrato de erro já existente.

## Referência e limites

O Python fornece casos comparativos, mas não é um oráculo absoluto: o cache-dir já é efetivo e o paralelismo adaptativo já redimensiona as tarefas em voo, e o Rust passou a ter cache de metadados com `--cache-dir`. O que ainda falta no Rust é expiração/invalidação do cache e o redimensionamento do paralelismo por quadro. Fixtures sintéticas contêm expectativas próprias; capturas reais sanitizadas e validação em Linux/Windows permanecem pendentes. Nenhuma fase é aprovada apenas pela criação do contrato ou pela presença de uma dependência Cargo.
