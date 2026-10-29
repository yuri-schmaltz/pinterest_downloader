"""Configuração compartilhada do pytest.

O código-fonte vive em ``src/`` e usa imports planos (``from json_logger
import ...``), ou seja, os módulos são resolvidos como top-level e não como
um pacote. Por isso ``src/`` precisa estar no ``sys.path``.

Sem isto, todo teste explode na coleta com::

    ModuleNotFoundError: No module named 'pinterest_board_dl'

O mesmo ajuste existe em três lugares, de propósito (redundância barata
contra breakage silencioso):

1. aqui (``conftest.py``) — cobre qualquer invocação do pytest;
2. em ``pyproject.toml`` (``[tool.pytest.ini_options] pythonpath``) — cobre
   o pytest >= 7 rodando a partir da raiz do projeto;
3. no ``sys.path.insert`` de cada arquivo de teste — cobre a execução
   direta (``python tests/test_x.py``), que o conftest não cobre.
"""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
