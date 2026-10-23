# Pinterest Pro Downloader — extensão

Extensão do navegador (Chrome / Firefox, Manifest V3) que baixa as imagens
dos pins de uma página do Pinterest com um clique.

Não tem relação com o resto do repositório: é JavaScript puro e não precisa
de Python nem do scraper. A CLI e a GUI são o outro produto — independentes.

---

## Como instalar

### Chrome / Edge / Brave (descompactado)

1. Baixe o `pinterest-pro-downloader-chrome-*.zip` da página de releases
2. Descompacte
3. `chrome://extensions` → **Modo do desenvolvedor** (canto superior direito)
4. **Carregar sem compactação** → selecione a pasta descompactada

### Firefox

1. Baixe o `pinterest-pro-downloader-firefox-*.xpi` dos releases
2. `about:debugging#/runtime/this-firefox` → **Carregar extensão temporária**
3. Selecione o `.xpi`

> O `.xpi` publicado **não é assinado**. O Firefox exige assinatura para
> distribuição permanente; para uso temporário, o modo de depuração resolve.

---

## Como usar

1. Abra uma página de quadro ou de perfil do Pinterest
2. Clique no botão flutuante vermelho, no canto inferior direito
3. A extensão rola a página, coleta as imagens e baixa a melhor resolução
   de cada pin

O botão mostra o progresso: quantas imagens foram encontradas e quantos
downloads foram iniciados.

### Opções

Pelo popup (ícone da extensão na barra do navegador):

| Opção | O que faz |
|---|---|
| **Pasta de destino** | onde os arquivos são salvos |
| **Quantidade máxima de pins** | `0` = sem limite |
| **Downloads paralelos** | quantos downloads ao mesmo tempo |

As configurações ficam salvas no `storage` da extensão.

---

## Estrutura

```
extension/
├── manifest.json        # Manifest V3
├── content.js           # content script: coleta, scroll, download
├── background.js        # service worker: coordena os downloads
├── popup.html / .js     # interface do popup
├── lib/
│   ├── i18n.js          # traduções (en, es, pt_BR) -> window.__pbdI18n
│   └── pin_utils.js     # helpers de URL de pin -> window.__pbdPinUtils
└── _locales/
    ├── en/messages.json
    ├── es/messages.json
    └── pt_BR/messages.json
```

### A ordem de carregamento importa

O `manifest.json` declara:

```json
"content_scripts": [{ "js": ["lib/i18n.js", "lib/pin_utils.js", "content.js"] }]
```

`content.js` lê `window.__pbdI18n` e `window.__pbdPinUtils` **no load**. Se
os helpers vierem depois, a extensão perde as traduções e as funções de URL
(variável `undefined`, e o download para de funcionar).

> Isso não é CHECKOUT puramente teórico: o `lib/i18n.js` chegou a faltar do
> repositório inteiro, porque a regra `lib/` do `.gitignore` engolia o
> diretório. O build saía sem o arquivo e a extensão não carregava. Hoje o
> CI falha o build se qualquer arquivo referenciado pelo manifest estiver
> ausente ou não versionado.

---

## Permissões

| Permissão | Para quê |
|---|---|
| `downloads` | baixar os arquivos |
| `activeTab` | agir na aba atual |
| `scripting` | injetar o content script sob demanda |
| `storage` | guardar as opções |
| `https://*.pinterest.com/*` | ler a página do Pinterest |
| `https://*.pinimg.com/*` | acessar as imagens |

---

## Desenvolvimento

```bash
# testes das traduções (Node puro, sem dependências)
node tests/test_extension_i18n.js

# testes das funções de URL (Node puro)
node tests/test_extension_pins.js

# teste de integração: os scripts reais numa página real, num browser real
python -m pytest tests/test_extension_integration.py -v

# empacotar
bash scripts/build_release.sh
```

Depois de alterar qualquer arquivo, **recarregue a extensão** em
`chrome://extensions` e **recarregue a aba do Pinterest** — o content script
só é injetado em abas abertas depois do carregamento.

### Checklist antes de publicar

- [ ] `node tests/test_extension_i18n.js` passa
- [ ] `node tests/test_extension_pins.js` passa
- [ ] `python -m pytest tests/test_extension_integration.py` passa
- [ ] toda chave de `_locales/pt_BR/messages.json` tem entrada no dicionário
      de fallback do `lib/i18n.js` (o teste cobre isso)
- [ ] a versão do `manifest.json` bate com o `pyproject.toml`
      (`python scripts/sync_version.py --check`)
- [ ] o `lib/` novo está versionado (`git ls-files extension/lib`)
