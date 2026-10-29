# Pinterest Pro Downloader v2.0.0 — Release Notes

## 🎉 Initial Public Release

Esta é a primeira versão pública da extensão Pinterest Pro Downloader para Chrome e Firefox.

## ✨ Funcionalidades

- **Download em alta resolução** — converte thumbnails (`236x`, `474x`, `564x`, `736x`, `1200x`) para a versão `originals` original
- **Auto-scroll** — rola automaticamente a página para carregar todas as imagens antes de baixar
- **Lazy-load support** — captura imagens que ainda não terminaram de carregar (via `data-src`)
- **Fila inteligente** — limite de concorrência configurável (1–12 paralelos)
- **Filenames descritivos** — usa o Pin ID do Pinterest, com fallback FNV-1a
- **Pasta de destino configurável** — salva em qualquer subpasta de `Downloads/`
- **Dedup automático** — múltiplos harvests não baixam a mesma imagem duas vezes
- **Internacionalização** — Português (pt-BR), Inglês (en), Espanhol (es)
- **Badge counter** — mostra downloads iniciados no ícone da extensão
- **Cross-browser** — Chrome, Brave, Edge e Firefox 121+

## 📦 Instalação

### Chrome / Brave / Edge
1. Acesse `chrome://extensions/`
2. Ative o **Modo do desenvolvedor**
3. Clique em **Carregar sem compactação** e selecione a pasta `extension/`

### Firefox 121+
1. Acesse `about:debugging#/runtime/this-firefox`
2. Clique em **Carregar extensão temporária**
3. Selecione o arquivo `manifest.json`

## 🔒 Privacidade

- **Sem coleta de dados** — nenhum analytics, tracking ou servidor remoto
- **Sem modificação do Pinterest** — apenas lê URLs de imagens já carregadas
- Permissões mínimas: `downloads`, `activeTab`, `scripting`, `storage`

## 🐛 Limitações conhecidas

- Pinterest login walls: algumas páginas exigem login. Faça login antes de usar.
- Vídeos: a extensão baixa o thumbnail estático, não o vídeo `.mp4`/`.mov`.

## 📝 Licença

MIT