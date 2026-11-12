# Plano de estabilização

Atualizado em **2026-11-06**, sobre o clone da `main` em `688243c`. Alterações descritas abaixo são locais; não representam publicação ou execução de CI remota.

## Correções desta revisão

- [x] Conectar a CLI Rust à coleta de pins do HTML `__PWS_DATA__` e à descoberta de quadros em perfis.
- [x] Documentar ausência de JavaScript, scroll, paginação e login no Rust.
- [x] Aplicar `--max-pins`, `--no-cache` e `--no-rate-limit` no downloader Rust.
- [x] Rejeitar workers/limites zero e retornar erro para extração vazia ou downloads incompletos na CLI.
- [x] Gravar novas mídias em arquivos temporários antes da publicação, em Python e Rust.
- [x] Ignorar temporários e colisões de prefixo no cache de mídia.
- [x] Encaminhar URLs de quadro único na CLI Python para `download_board`.
- [x] Adicionar regressões com HTTP local para streams interrompidos, retry, cache e extração.
- [x] Incluir checks Rust no workflow de CI e builds Linux/Windows no workflow de release.
- [x] Incluir Rust, spec PyInstaller, hooks e documentação no pacote source.
- [x] Sincronizar versões dos crates/lockfile com o manifest da extensão.
- [x] Corrigir documentação operacional e normalizar finais de linha LF.
- [x] Encaminhar `--cache-dir` ao resolvedor de metadados; o padrão passou a ser o cache do sistema (XDG/AppData).
- [x] Redimensionar de fato o paralelismo quando o gerenciador adaptativo ajusta o número de workers.
- [x] Trocar `datetime.utcnow()` por `datetime.now(timezone.utc)`, preservando o formato dos timestamps.
- [x] Entregar o cache de metadados no Rust, com `--cache-dir`, `--no-metadata-cache` e o mesmo formato de arquivo do Python.
- [x] Tornar o teste do rate limiter Rust determinístico, medindo esperas do limitador em vez de relógio.
- [x] Substituir o token bucket Rust por janelas deslizantes com backoff exponencial e `Retry-After` completo.
- [x] Processar vários quadros em paralelo no Rust, com `--boards-workers` e um browser por worker.

## Plano de paridade Rust

O detalhamento da evolução para paridade do motor, CLI e GUI está em [docs/PLANO-PARIDADE-RUST.md](docs/PLANO-PARIDADE-RUST.md), com etapas, dependências, critérios de aceite e estimativas. É um plano de trabalho; seus marcos ainda não foram entregues.

## Pendências, em ordem de prioridade

1. **Compatibilidade Pinterest real:** capturar HTML/payloads reais, versionar fixtures sem dados privados e validar quadros/perfis atuais. Os testes locais não comprovam essa compatibilidade.
2. **Paridade Rust em execução:** adapter Chromium/CDP, coleta por DOM/rede/scroll, eventos e CLI já têm regressões locais. Validar o Pinterest real, login interativo, cache persistente, controle de concorrência e GUI conforme o plano detalhado.
3. **Distribuição:** executar os workflows alterados após push e testar os artefatos Linux/Windows. Não foram publicados nesta revisão.
4. **Integridade de arquivos antigos:** decidir se o reuso deve exigir tamanho/hash ou metadados persistidos. Arquivos existentes com conteúdo ainda são reutilizados sem verificação retrospectiva.
5. **Extensão:** separar manifest Firefox, validar extensão instalada em browsers reais, assinar XPI e preparar Chrome Web Store.
6. **Cache Python:** o `--cache-dir` já é encaminhado ao resolvedor e o cache padrão é o do sistema. Falta o cache de metadados versionado e a invalidação segura previstos no plano de paridade.
7. **Cache Rust:** entregue com `--cache-dir` e `--no-metadata-cache`, no mesmo formato do Python. Faltam versionamento, expiração e invalidação.
8. **Manutenção:** estabelecer MSRV Rust e avaliar dependências fixadas Python.

## Histórico

A documentação anterior registra estabilização Python, GUI em três etapas e v2.0.5 publicada em outubro de 2026. O PR #11 já foi integrado em `67329b1`. O histórico detalhado das ONDAs fica em `docs/`; suas métricas não descrevem automaticamente o checkout atual.

Veja [TEST_INFRA.md](TEST_INFRA.md) para resultados reproduzíveis e [HANDOFF.md](HANDOFF.md) para retomada e publicação.
