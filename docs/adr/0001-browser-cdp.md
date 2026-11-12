# ADR 0001 — Adapter Chromium e prova de compatibilidade

Data: 2026-11-06. Estado: decisão provisória validada localmente em Linux; Windows e Pinterest real pendentes.

## Evidência

A dependência original `chromiumoxide 0.5.7` compilou, iniciou Chromium e conseguiu cancelar execução, mas falhou na primeira navegação HTTP real com `data did not match any variant of untagged enum Message`, encerrando o handler CDP e causando `oneshot canceled`. O ambiente local usa Chrome for Testing 156.0.8078.4.

Após atualização para `chromiumoxide 0.9.1`, os testes de navegação, JSON carregado com atraso, feed virtualizado, cookies entre páginas, fechamento e cancelamento passaram. O handler é executado por Tokio. A criação de uma dependência opcional sem esses testes não teria revelado a falha.

## Decisão

Isolar a biblioteca em `pinterest-browser`. O crate não depende de Python, Node, GUI nem dos parsers Pinterest. Ele oferece sessão, páginas, execução JS e snapshots com captura JSON limitada. O motor em `pinterest-core` decide como interpretar e coletar os dados.

Cada sessão usa perfil temporário exclusivo por padrão. Perfil persistente é opt-in pela API, ainda sem fluxo CLI de gerenciamento. A sandbox permanece habilitada salvo opção explícita; os testes locais usam `no_sandbox` em ambiente isolado. HTTPS é verificado. O fechamento tenta terminar normalmente, depois força e aguarda o filho dentro de um prazo limitado. A sessão preserva cookies entre páginas.

O CDP tem limites de buffer; a captura sinaliza truncamento e requisições JSON pendentes, que impedem inferir completude. Pins coletados no DOM continuam disponíveis quando não há metadados interceptados. Um snapshot HTTP explícito nunca é rotulado completo só por conter pins.

Uma página que não mudou de altura e não trouxe links novos parece um feed que não chegou. A coleta só pode ser declarada estável quando o documento terminou de parsear, não há payload JSON em voo e o quadro já entregou pins ou traz marcador de fim explícito. Sem isso, um quadro lento é reportado como vazio, que é uma resposta errada e não apenas incompleta.

## Validação e limites

Testes em `crates/pinterest-browser/tests/lifecycle.rs`, `crates/pinterest-core/tests/dynamic_collection.rs` e `crates/pinterest-cli/tests/commands.rs` usam fixtures locais compartilhadas. A CI adiciona execução explícita dos testes de browser em Linux e Windows; esses jobs ainda não foram executados remotamente nesta revisão.

Não há comprovação de login autenticado headful, compatibilidade Pinterest atual, instalação gerenciada de Chromium nem MSRV do workspace completo. A versão de Chromium usada em releases deve ser validada contra esses testes antes de mudar. A escolha de framework GUI permanece pendente e não é aprovada por este ADR.
