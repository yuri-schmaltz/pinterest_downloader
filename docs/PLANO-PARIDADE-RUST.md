# Plano de paridade funcional Python → Rust

**Data:** 2026-11-06. **Estado:** execução iniciada; paridade completa ainda não aprovada.

## Progresso da execução local

- P0: contrato em `CONTRATO-PARIDADE.md`, matriz rastreável em `tests/fixtures/parity/requirements.json` e fixtures locais compartilhadas criados. Capturas reais e congelamento final dos contratos ainda pendentes.
- P1: crate `pinterest-browser` com Chromium/CDP, descoberta de executável, perfis temporários isolados, eventos de rede, cookies e fechamento/cancelamento. Prova Linux executada; Windows depende da CI adicionada. Decisão em `adr/0001-browser-cdp.md`.
- P2: coleta dinâmica de perfil/quadro por JSON, DOM e scroll, incluindo feed virtualizado; resultado distingue fim explícito, limite, estabilidade e timeout. A estabilidade só é declarada quando o documento terminou de parsear, não há payload JSON em voo e o quadro já entregou pins ou traz marcador de fim; um feed lento não pode ser reportado como quadro vazio. Atribuição de origem e critérios de fim no Pinterest real ainda pendentes.
- P3: integração de cookies, resolução HTTP pela página do pin/metatags e protocolo de login/continuação/cancelamento iniciados. Login headful real, persistência e renovação de sessão ainda pendentes.
- P5: motor compartilhado, canal limitado de eventos, CLI com modos auto/browser/http, opções de coleta, JSONL, códigos de saída e Ctrl+C. Cache de metadados entregue com `--cache-dir` e controle próprio `--no-metadata-cache`; paralelismo entre quadros entregue com `--boards-workers` e janelas de rate limiting com `Retry-After`. Workers adaptativos por CPU/memória ainda pendentes.
- P4/P6/P7/P8: não entregues como marcos completos. Nenhum artefato foi publicado nem a paridade foi declarada.

A matriz diferencia código implementado de requisito verificado integralmente. `python scripts/check_parity.py --require-complete` deve falhar enquanto houver itens obrigatórios pendentes.
**Base:** checkout local iniciado em `688243c`, incluindo as correções locais registradas em `PLANO-ESTABILIZACAO.md`.

## 1. Resultado esperado e escopo

A implementação Rust deve permitir os mesmos trabalhos hoje oferecidos pela CLI e pela GUI Python: descobrir quadros, escolher quais baixar, coletar pins em páginas dinâmicas, resolver mídias, autenticar manualmente quando necessário, baixar com controle de concorrência e recuperar falhas, com progresso e resultados verificáveis.

A entrega terá dois marcos distintos:

- **Paridade do motor e da CLI:** coleta dinâmica, sessão autenticada, cache, opções, logs, recuperação, concorrência e distribuição testadas.
- **Paridade completa do produto:** tudo acima, mais GUI Rust com o fluxo Perfil → Quadros → Download e os comportamentos da GUI Python.

O primeiro marco não autoriza declarar a substituição completa do Python. A extensão JavaScript permanece independente e não integra esta migração.

Paridade significa equivalência observável em cenários definidos. Não exige portar funções linha a linha, repetir bugs Python nem garantir coleta de conteúdo que a conta não pode acessar. A implementação final não deve depender de Python ou Node em runtime; Chromium continua sendo uma dependência externa que precisa ser gerenciada.

## 2. Referência observada no checkout

| Capacidade | Referência Python | Rust atual | Entrega necessária |
|---|---|---|---|
| Quadro único e perfil | `download_board`, `download_user_boards` | HTML inicial | Mesmos fluxos em páginas dinâmicas |
| Descoberta de quadros | `collect_board_urls` | JSON inicial, sem capas | Scroll, filtros, títulos, capas e contagens |
| Coleta de pins | `collect_pin_links` | `__PWS_DATA__` inicial | DOM + respostas de rede + scroll |
| Metadados | PWS, ResourceResponse, GraphQL | PWS parcial | Normalização dos formatos observados |
| Resolução de mídia | Interceptação, cache e página do pin | URL embutida | Cadeia de resolução e fallback |
| Login manual | Browser visível e confirmação CLI/GUI | Ausente | Sessão e continuação sem bloquear o runtime |
| Perfis privados/login obrigatório | Erro e orientação | Erro genérico de extração | Estados e mensagens específicos |
| Downloads | Paralelos, retry, verificação e recuperação | Streaming, retry e temporários | Verificação final e recuperação por pin |
| Cache | Mapa persistido pin → URL | Reuso de arquivos | Cache de metadados e política de invalidação |
| Concorrência entre quadros | `boards_workers` | Quadros sequenciais | Limites separados para browser/resolução/download |
| Workers adaptativos | CPU, memória, sucesso, latência | Ausente | Ajuste efetivo da concorrência em execução |
| Rate limiting | Janelas de segundo/minuto/hora | Token bucket | Política equivalente, backoff e métricas |
| Logs e métricas | JSON por fases, estatísticas | Texto de tracing | Eventos e arquivos estruturados |
| Progresso/cancelamento | Callbacks e sinais da GUI | Resumo final | Eventos tipados e cancelamento cooperativo |
| GUI | Perfil, seleção, capas, pasta, progresso, login | Ausente | Aplicação desktop Rust |
| Distribuição | PyInstaller, AppImage, DEB, Windows | Workflow CLI Linux/Windows definido | CLI/GUI e Chromium validados em máquinas limpas |

A referência é o comportamento do código, confrontado com cenários e expectativas independentes. A suíte local registrada tem 218 testes Python e 53 Rust; isso não comprova compatibilidade atual com o Pinterest.

Divergências conhecidas a resolver no contrato:

- Python e Rust diferem em defaults, saída em disco e semântica de `--no-cache`.
- Rust tem cache de metadados e `--cache-dir`, mas ainda sem expiração nem invalidação segura; o Python também não tem.
- Rust redimensiona o paralelismo entre quadros, mas ainda não ajusta o número de tarefas em voo por CPU e memória como o `--adaptive-workers` do Python.
- Um HTML vazio ou parcial não prova que um quadro está vazio ou completo.
- Reuso de arquivos não vazios não prova integridade retrospectiva.

## 3. Arquitetura proposta

Manter uma única implementação do fluxo, consumida pelas duas interfaces:

```text
pinterest-cli ─┐
              ├─ motor de operações e eventos ─┬─ coleta HTTP
pinterest-gui ┘                               ├─ coleta Chromium/CDP
                                              ├─ normalização e resolução de mídias
                                              ├─ sessão/cache/arquivos
                                              └─ escalonamento, download e verificação
```

Divisão sugerida, evitando criar um crate para cada helper:

- `pinterest-core`: modelos, validação, parsers puros, resolução, cache, downloader, eventos e orquestração. Sem imports da GUI.
- `pinterest-browser`: inicialização/descoberta de Chromium, CDP, contextos, páginas, respostas de rede, scroll, autenticação e encerramento.
- `pinterest-cli`: argumentos, apresentação, sinais do sistema e códigos de saída.
- `pinterest-gui`: estado da interface e apresentação dos mesmos eventos.
- `tests/fixtures/parity/`: HTML, payloads, mídias e resultados esperados compartilhados pelos testes.

O coletor HTTP permanece como otimização. O modo automático só pode encerrar a coleta por HTTP se houver evidência suficiente para o contrato de completude; encontrar alguns pins não basta. Caso contrário, usa Chromium. Um modo HTTP explícito deve informar que o resultado pode ser parcial.

### Contratos centrais

Definir antes de implementar o browser:

- `BoardMetadata` e `PinMetadata` com IDs estáveis, origem, título, thumbnail, contagem opcional, candidatos de mídia e procedência dos dados.
- `RunOptions` com campos separados para coleta, sessão, cache, limites e apresentação; defaults em um único lugar.
- `RunEvent` tipado: descoberta, início de quadro, coleta, resolução, início/progresso/falha de mídia, espera por limite, login necessário, conclusão e cancelamento.
- Eventos levam `run_id`, `board_id` e `pin_id` quando aplicáveis; estado de metadados pertence à operação/quadro, sem cache global mutável compartilhado inadvertidamente.
- Resultado distingue descobertos, resolvidos, novos downloads, reutilizados, verificados, falhos e ignorados. Inclui `completion_reason` e indicador de completude conhecida/parcial/desconhecida.
- Canais de eventos limitados e política de agregação de progresso para impedir que uma GUI lenta aumente memória indefinidamente. Erros e eventos terminais não podem ser descartados.
- Um token de cancelamento por operação, propagado a navegação, espera de login, limitador, retry, filas e streaming.

### Decisões de dependências

**Browser:** avaliar primeiro `chromiumoxide`, já presente como dependência opcional, mediante prova de conceito. Sua documentação descreve automação CDP e o processamento do handler de eventos. A dependência atual `0.5` não deve ser tomada como versão adequada sem teste e avaliação de atualização. Fonte: [chromiumoxide](https://github.com/mattsse/chromiumoxide/blob/main/README.md).

A escolha é aprovada apenas se demonstrar: execução de JavaScript, leitura de respostas JSON, cookies/contextos, browser visível, encerramento e funcionamento Linux/Windows. Caso falhe, registrar uma decisão arquitetural e avaliar outro cliente CDP Rust antes de construir a coleta sobre ele. Não introduzir um subprocesso Python como solução permanente.

**GUI:** candidato inicial `egui/eframe`, sujeito a uma prova de conceito de acessibilidade, teclado, thumbnails, seletor de diretório, diálogos e execução em máquina limpa. `eframe` é o framework oficial da integração egui e suporta aplicação nativa. Fonte: [eframe](https://github.com/emilk/egui/blob/main/crates/eframe/README.md). Se não atender, comparar uma alternativa em uma decisão documentada; a fase da GUI não deve ficar dependente de escolha implícita.

Versões exatas, MSRV e política de atualização serão fixados após essas provas. Não escolher uma versão apenas porque é a mais recente.

## 4. Etapas, entregas e critérios de aceite

### P0 — Congelar o contrato de paridade e a referência

**Esforço estimado:** 2–3 dias de engenharia. **Dependências:** nenhuma.

Entregas:

1. Matriz de funcionalidades com um ID por requisito, cenário, expectativa e teste correspondente.
2. Inventário de argumentos, defaults, eventos, formatos de cache, layout em disco e falhas Python/Rust.
3. Fixtures sintéticas determinísticas e um conjunto inicial de capturas reais sanitizadas: quadro, perfil, pin, login, payloads PWS/ResourceResponse/GraphQL. Registrar data, origem e limites de cada captura.
4. Expectativas explícitas para IDs, relação quadro → pin, resolução, nomes e totais; Python é referência comparativa, não o único oráculo.
5. Decisão sobre compatibilidade da CLI e migração dos dados locais.

**Aceite:** todo item da matriz tem cenário e critério verificável. Bugs Python conhecidos estão identificados. A referência sintética roda sem acessar o Pinterest; capturas reais não contêm cookies, tokens ou dados privados.

### P1 — Contratos do motor e prova de browser

**Esforço:** 3–5 dias. **Depende de:** P0.

Entregas:

1. Modelos, erros, eventos, resultados e cancelamento compartilhados.
2. Adapter de browser com lançamento headless/headful, criação de contexto/página, execução de JS e captura de resposta.
3. Descoberta de Chromium por caminho configurado, instalação gerenciada ou browser suportado do sistema, com erro acionável.
4. Prova Linux/Windows e decisão documentada sobre cliente CDP, versão de Chromium e MSRV.

**Aceite:** navegar em fixture dinâmica, capturar JSON carregado após a navegação, fechar durante uma espera e repetir iniciar/fechar sem deixar processos filhos. Teste sem Chromium produz orientação de instalação; browser não pode encerrar silenciosamente enquanto há tarefas pendentes.

### P2 — Coleta dinâmica completa de perfis e quadros

**Esforço:** 6–10 dias. **Depende de:** P1.

Entregas:

1. Parsers puros para os formatos de rede observados e JSON inicial; fallback DOM para links e metadados.
2. Listagem de quadros com nome, URL, capa e contagem opcional; exclusão de navegação, quadros de outros perfis e duplicatas.
3. Scroll guiado por novos IDs, crescimento da página, atividade de rede e sinais de fim. Processar cursores/paginação quando presentes nos dados observados, sem depender exclusivamente de um endpoint não documentado.
4. Critérios de parada distintos: fim comprovado, limite pedido, estabilidade, timeout, bloqueio, cancelamento e erro.
5. Identificação da origem do feed para não misturar recomendações “Mais como esse” com pins do quadro.
6. Limites de duração e memória, preservando resultados parciais quando a coleta não termina.

**Aceite:** fixtures com múltiplas páginas, DOM virtualizado, carregamento atrasado, duplicatas e recomendações entregam exatamente os IDs esperados. `--max-pins N` não excede N por quadro. Timeout/bloqueio gera resultado parcial/desconhecido explícito, sem declarar todos os pins coletados.

### P3 — Sessão, login manual e resolução de mídias

**Esforço:** 5–8 dias. **Depende de:** P2.

Entregas:

1. Detectar login necessário, perfil/quadro privado sem acesso, inexistência, bloqueio e erro de rede como situações distintas quando houver evidência suficiente. Estado ambíguo continua ambíguo.
2. Abrir browser visível para login manual e receber confirmação pela CLI ou GUI. Manter o contexto autenticado nas operações seguintes.
3. Reusar o browser/contextos entre quadros, isolando o estado de cada coleta.
4. Resolver mídia por metadados interceptados → JSON da página → visita do pin e metatags/DOM. Validar candidatos com fallback para resolução disponível.
5. Tratar formatos já suportados pelo Python, incluindo MP4 quando houver URL direta; streaming HLS/DASH novo fica fora da paridade básica.
6. Transferir ao cliente HTTP cookies aplicáveis por domínio/caminho e headers necessários, sem colocá-los em logs. Persistência de sessão é opt-in e apagável.

**Aceite:** cenário de login termina a operação na mesma sessão; cancelar a espera encerra corretamente. Sessão expirada pede nova autenticação sem perder arquivos concluídos. Os formatos observados produzem as mídias esperadas, sem atribuir uma mídia de outro pin. URLs expiradas podem ser resolvidas novamente.

### P4 — Cache, integridade, recuperação e compatibilidade dos arquivos

**Esforço:** 5–8 dias. **Depende de:** P3; parsers e armazenamento podem começar após P1.

Entregas:

1. Cache versionado pin → metadados/candidatos de mídia, com gravação atômica e isolamento entre execuções. Escolher JSON com escrita serializada ou banco após avaliar concorrência; não manter múltiplos writers sem coordenação.
2. Caminhos de cache/config por sistema e `--cache-dir` efetivo. Definir expiração, invalidação e comportamento em cache corrompido.
3. Contrato de `--no-cache` para metadados e uma opção separada para forçar novo download de mídia. Preservar a semântica antiga Rust por compatibilidade/depreciação documentada, sem alterá-la silenciosamente.
4. Adotar `pins/<usuario>/<quadro>/` como layout de compatibilidade ou oferecer importação/migração explícita do layout Rust atual. Nomes por ID evitam colisões; títulos não são identidade.
5. Preservar temporários, streaming e retry existentes; validar tipo, tamanho esperado quando disponível e término do stream. Gravar metadados de conclusão para não confundir arquivo parcial com mídia completa.
6. Verificação pós-download, nova resolução das falhas e número limitado de tentativas de recuperação. Não repetir indefinidamente uma URL expirada.
7. Política explícita para arquivos antigos sem registro de integridade: importar/verificar, baixar de novo ou reutilizar com status “não verificado”.

**Aceite:** segunda execução não repete trabalho válido; cache corrompido não apaga downloads. Interrupção, pouco espaço, permissão negada e encerramento do processo não publicam novos arquivos incompletos como concluídos. Reexecução recupera falhas sem duplicar nomes nem atribuir sucesso a um prefixo de outro pin. Cache-dir diferente isola as operações.

**Entregue até agora:** itens 2 e 3 parciais e item 1 parcial. Existe `crates/pinterest-core/src/cache.rs` com persistência JSON em `.pinterest_cache.json`, gravação atômica (arquivo temporário e rename), isolamento por diretório, descarte de cache corrompido e reuso na reexecução; a CLI tem `--cache-dir` e `--no-metadata-cache`, e o formato do arquivo é o mesmo do Python. Faltam versionamento do cache, expiração/invalidação e a migração de layout do item 4.

### P5 — Concorrência, rate limiting, logs e compatibilidade CLI

**Esforço:** 6–10 dias. **Depende de:** contratos P1, coleta P2 e resolução P3; aceite final após P4.

Entregas:

1. Limites independentes de páginas/contextos, quadros, resolução e downloads; filas limitadas e orçamento global para evitar multiplicação de `boards_workers × workers`.
2. Ajuste adaptativo efetivo das tarefas em voo com CPU, memória, latência e falhas; redução por 429 e recuperação gradual. Limites fixos permanecem disponíveis.
3. Política configurável para janelas segundo/minuto/hora, além do burst; `Retry-After` em segundos e data HTTP, backoff limitado e estatísticas. Valores Python são referência de configuração, não limites oficiais comprovados do Pinterest.
4. Cancelamento de espera de taxa e retry; 429 de um host não deve congelar indevidamente tarefas de outro host.
5. Equivalência das opções Python: `--user`, `--out`, `--headful`, `--manual-login`, `--max-pins`, `--scroll-pause`, `--workers`, `--boards-workers`, `--cache-dir`, `--no-cache`, `--adaptive-workers`, `--rate-limiting`, `--json-log`, `--log-file`, `--version` e ajuda. Manter aliases Rust existentes e tratar ambiguidades.
6. Logs JSON por fases e arquivos de métricas; documentar compatibilidade do JSON Python e formato de streaming, se houver. Progresso vai para stderr quando stdout for estruturado.
7. Códigos de saída documentados para sucesso, argumento inválido, browser ausente, autenticação, alvo inacessível, resultado parcial/falha, extração ambígua e cancelamento. O código atual Rust genérico pode mudar apenas com nota de migração.

**Aceite:** testes medem o teto real de tarefas; mudar workers altera concorrência efetiva. Usar relógio controlado para janelas/backoff, sem testes que esperem minutos. Logs são JSON válido, totais conciliam com arquivos e não expõem sessão. CLI tem testes como subprocesso para todos os códigos e flags, incluindo interrupção durante coleta e download.

### P6 — GUI Rust com paridade de fluxo

**Esforço:** 10–15 dias. **Depende de:** prova de GUI após P1; conclusão depende do motor P2–P5.

Entregas:

1. `pinterest-gui` com estado explícito das três etapas e decisões documentadas sobre framework/renderização/acessibilidade.
2. Perfil: entrada, validação, descoberta assíncrona, erro e tentativa novamente.
3. Quadros: busca, seleção individual/todos, capas quadradas sem distorção, título/contagem, pasta e workers. Listas grandes precisam virtualização e cache limitado de thumbnails.
4. Download: progresso por quadro e total, logs, arquivos novos/reutilizados/falhos, cancelar e resumo de resultado parcial.
5. Login: diálogo para abrir browser e continuar/cancelar; cancelar também destrava a tarefa de autenticação.
6. Tema escuro, navegação por teclado, foco, escala de tela e mensagens legíveis. Downloads não podem rodar na thread da interface.
7. Compartilhar o motor; a GUI não chama a CLI por subprocesso nem mantém um segundo scraper.

**Aceite:** a jornada Perfil → selecionar subconjunto → baixar gera somente as mídias selecionadas. Filtro/seleção não perdem estado indevidamente. A interface continua responsiva com coleta/streaming em execução. Cancelamento é observado em até 2 segundos nas operações sob controle da aplicação, sem esperar o término de um timeout de rede; o encerramento forçado de um browser travado tem limite separado de até 5 segundos. Fluxos de erro, login, cancelamento e repetição são testados em Linux e Windows.

### P7 — Validação de paridade e desempenho

**Esforço:** 3–5 dias, além dos testes incorporados em cada etapa. **Depende de:** P5 para CLI; P6 para produto completo.

Entregas:

1. Runner de comparação sobre as mesmas fixtures e respostas reproduzíveis: lista de quadros, IDs, associação quadro/pin, resolução/formato, arquivos, totais, eventos terminais e erros.
2. Casos reais controlados: quadro pequeno, quadro com várias páginas, perfil com vários quadros, conteúdo com mídia variada e login manual em conta de teste. Registrar ambiente, data e resultados; mudanças do Pinterest entre execuções são analisadas, não contadas automaticamente como regressão Rust.
3. Testes de resiliência: 429, 5xx, timeout, perda de rede, redirecionamentos, URL expirada, disco cheio, cache corrompido, cancelamento e browser que fecha inesperadamente.
4. Benchmarks separados para tempo de coleta, resolução, download, CPU e memória, incluindo o Chromium. Registrar execução fria e quente e versões dos browsers.

**Aceite:** 100% dos requisitos obrigatórios da matriz têm evidência aprovada; nos cenários determinísticos, igualdade exata dos IDs esperados e zero mídias extraviadas/parciais publicadas. Casos reais têm resultados revisados e limites declarados. Nenhuma pendência obrigatória pode ser dispensada apenas porque os testes Python também falham. Metas de desempenho são fixadas após a medição de referência; superioridade de velocidade não é pré-condição nem promessa de paridade.

### P8 — Distribuição, documentação e transição

**Esforço:** 3–5 dias. **Depende de:** P7.

Entregas:

1. CI Rust Linux/Windows para unitários, HTTP local, browser e CLI; testes GUI em ambiente com display virtual quando possível e roteiro de validação visual nativa.
2. Builds com lockfile e toolchain/MSRV definidos. CLI e GUI para Windows e Linux, incluindo AppImage/DEB onde fazem parte da distribuição atual. macOS exige job e validação próprios antes de ser declarado suportado.
3. Estratégia documentada de Chromium: bundle versionado ou download gerenciado com verificação, além de caminho externo. Rust não elimina o tamanho nem os requisitos de sistema do browser.
4. Smoke tests dos pacotes em ambientes sem Python/Node: abrir GUI, localizar browser, descobrir quadros em fixture, baixar mídia e cancelar. Publicar checksums e instruções de atualização/remoção.
5. README, ajuda, runbooks, notas de versão e migração de cache/paths alinhados aos artefatos realmente produzidos.
6. Publicar primeiro como candidata de paridade. Manter Python disponível até aprovação do marco de produto completo e execução real dos workflows no commit final.

**Aceite:** artefatos baixados da release candidata passam pelos cenários em máquinas limpas Linux/Windows. Fonte distribuída compila e contém fixtures, crates, manifests, lockfile e instruções. Nenhum requisito depende apenas de “build verde”.

## 5. Ordem de execução e estimativa

Caminho principal: **P0 → P1 → P2 → P3 → P4/P5 → P6 → P7 → P8**. As provas de GUI, fixtures e armazenamento podem avançar depois de estabilizados os contratos; a coleta dinâmica é o principal risco técnico inicial.

| Marco | Etapas | Evidência para encerrar |
|---|---|---|
| Referência e viabilidade | P0–P1 | Matriz rastreável, browser/GUI avaliados e fixtures aprovadas |
| Paridade motor/CLI | P2–P5 + validação correspondente de P7 | CLI completa, coleta dinâmica, login, cache, logs e regressões |
| Paridade de produto | P6 + P7 integral | Jornadas da GUI e todos os requisitos obrigatórios aprovados |
| Candidata distribuível | P8 | Pacotes reais em máquinas limpas e documentação alinhada |

Soma inicial: **43–69 dias de engenharia**, aproximadamente **9–14 semanas para uma pessoa em dedicação integral**, antes de contingência. Planejar mais **20–30% de reserva** para mudanças do Pinterest, comportamento CDP e empacotamento/GUI; janela orientativa de **11–18 semanas**. São estimativas, não datas prometidas. Reestimar ao concluir P1 e P3 com evidência real. Não assumir que adicionar pessoas reduz proporcionalmente o caminho crítico.

## 6. Riscos e respostas

| Risco | Resposta planejada |
|---|---|
| Layout/payload Pinterest muda | Parsers isolados, capturas datadas, fixtures reais e validação controlada |
| Coleta incompleta parece sucesso | Resultado com razão de término e completude explícita; verificação por IDs |
| Recomendações contaminam quadro | Atribuição de origem dos feeds e fixtures negativas |
| Cliente CDP não atende | Prova P1 antes da coleta e adapter substituível |
| Sessão expira durante operação | Estado de autenticação, resolução renovável e preservação dos concluídos |
| Paralelismo satura RAM/browser | Orçamento global, filas limitadas e backpressure |
| GUI bloqueia ou cancela tarde | Runtime separado, eventos tipados e cancelamento propagado |
| Migração duplica/apaga arquivos | Importação explícita, registro por ID e testes com diretórios existentes |
| Pacote depende de ambiente do dev | Smoke tests em máquinas sem Python/Node e browser gerenciado |
| Documentação anuncia paridade cedo | Marcos CLI/produto distintos e matriz de requisitos bloqueante |

## 7. Checklist final de aprovação

- [ ] Matriz obrigatória inteiramente aprovada, com referências a testes e evidências.
- [ ] Perfil, quadro único e seleção de quadros coletam conteúdo dinâmico correto.
- [ ] Login manual e sessão expirada funcionam em CLI e GUI.
- [ ] Metadados, resolução original/fallback e mídias já suportadas pelo Python equivalentes.
- [ ] Cache, paths e migração preservam dados e têm semântica documentada.
- [ ] Recuperação, verificação e arquivos temporários resistem às falhas previstas.
- [ ] Opções, concorrência real, rate limiting, eventos, logs e totais validados.
- [ ] GUI em três etapas com seleção, thumbnails, progresso e cancelamento aprovada.
- [ ] Browser e aplicação encerram sem processos órfãos nos cenários testados.
- [ ] Comparação determinística e validação real controlada concluídas.
- [ ] CI remota e pacotes da candidata testados em Linux e Windows.
- [ ] Documentação e notas de migração refletem a release entregue.

Somente após esses itens a versão Rust pode ser declarada equiparada à versão Python como produto completo.
