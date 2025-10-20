# app-pinterest-dl

Ferramenta para baixar imagens de quadros do Pinterest, seja via linha de comando ou com uma interface gráfica em PyQt6.

## Recursos

- Download de um quadro específico ou de todos os quadros públicos de um usuário.
- Resolução automática da melhor imagem disponível para cada pin.
- Execução paralela configurável para acelerar a coleta e o download.
- Interface gráfica (PyQt6) com acompanhamento de progresso, histórico de quadros e cancelamento seguro.
- Suporte a login manual quando necessário (quadro privado/somente logados).

## Requisitos

- Python 3.10+
- [Playwright](https://playwright.dev/python/) e o navegador Chromium instalado (`playwright install chromium`).
- Dependências listadas em `requirements.txt`.

Instale os requisitos com:

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

> **Dica:** em ambientes sem interface gráfica disponível, utilize a flag `--headful` apenas quando realmente precisar depurar/login.

## Estrutura do repositório

```
.
├── pinterest_board_dl.py      # Núcleo reutilizável + CLI
├── pinterest_board_gui.py     # Interface gráfica em PyQt6
├── requirements.txt           # Dependências Python
├── README.md                  # Este guia
└── LICENSE
```

## Uso pela linha de comando

```bash
python pinterest_board_dl.py https://www.pinterest.com/<usuario>/<quadro>/
```

Para baixar todos os quadros públicos de um usuário:

```bash
python pinterest_board_dl.py --user usuario_pinterest
```

Opções úteis:

- `-o/--out`: define a pasta de saída (default: `./pins`).
- `--headful`: abre o navegador visível durante a coleta.
- `--manual-login`: pausa para que você faça login antes de coletar os pins.
- `--max-pins`: limita a quantidade de pins baixados por quadro.
- `--workers`: controla o paralelismo interno (resolução/download).
- `--boards-workers`: controla o número de quadros processados em paralelo.

## Uso pela interface gráfica

```bash
python pinterest_board_gui.py
```

A janela principal possui duas abas:

1. **Quadro único** – informe a URL completa do quadro que deseja baixar.
2. **Todos os quadros do usuário** – informe o usuário ou URL do perfil.

Configure as opções na seção "Opções de download" e clique em **Iniciar download**. O painel de progresso mostra o andamento do quadro atual, o total de quadros processados e o histórico dos quadros concluídos. O log detalhado exibe mensagens e eventuais avisos.

Se "Pausar para login manual" estiver ativado, quando necessário o aplicativo exibirá um aviso solicitando o login na janela aberta pelo Playwright; após concluir o login clique em **Continuar** para retomar o download.

O botão **Cancelar** solicita o término do processo atual de forma segura.

## Desenvolvimento

- O módulo `pinterest_board_dl.py` agora concentra toda a lógica em funções reutilizáveis (`download_board`, `download_user_boards`, etc.), permitindo integrações em outros projetos.
- Para executar testes rápidos de sintaxe, você pode usar `python -m compileall pinterest_board_dl.py pinterest_board_gui.py`.

Contribuições são bem-vindas!
