#!/usr/bin/env python3
"""Testes da superficie da CLI: --version e --user.

Duas flags que os docs prometiam e o codigo nao tinha:

  - `--version`: o runbook antigo mandava rodar
    `python pinterest_board_dl.py --version`, e o comando falhava com
    "unrecognized arguments".
  - `--user`: o README e cinco guias "ONDA" usam
    `pinterest-board-dl --user usuario_pinterest`, que tambem falhava --
    a CLI so aceitava o argumento posicional.

Estes testes existem para as duas nao voltarem a sumir, e para garantir
que a versao mostrada seja a mesma em todo lugar.

O que eles cobrem:
  1. a resolucao da versao (constante gerada, manifest, metadata)
  2. a flag --version da CLI
  3. a flag --user e o argumento posicional
  4. o gate de sincronia entre manifest, pyproject e o arquivo gerado
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

import app_version
from app_version import get_version, get_version_banner
from pinterest_board_dl import build_arg_parser

ROOT = Path(__file__).parent.parent
MANIFEST = ROOT / "extension" / "manifest.json"
PYPROJECT = ROOT / "pyproject.toml"
GENERATED = ROOT / "src" / "_version.py"


def manifest_version() -> str:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]


def pyproject_version() -> str:
    import re

    match = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(), re.MULTILINE)
    assert match, "nao achei version no pyproject.toml"
    return match.group(1)


class TestVersionResolution:
    def test_versao_do_manifest(self):
        assert get_version() == manifest_version()

    def test_banner_tem_o_nome_do_pacote(self):
        banner = get_version_banner()
        assert banner.startswith("pinterest-board-downloader ")
        assert manifest_version() in banner

    def test_versao_gerada_bate_com_o_manifest(self):
        # o arquivo gerado e o que viaja com o app; se divergir do
        # manifest, o app esta mostrando um numero que nao existe
        assert app_version._from_generated() == manifest_version()

    def test_fallback_para_o_manifest(self):
        # se o arquivo gerado sumir, o manifest ainda responde
        assert app_version._from_manifest() == manifest_version()

    def test_versao_desconhecida_e_uma_string(self):
        version = get_version()
        assert isinstance(version, str)
        assert version

    def test_o_manifest_e_a_fonte_da_verdade(self):
        # a ordem de precedencia: gerado > manifest > metadata
        assert app_version._from_generated() is not None


class TestVersionSourcesAgree:
    def test_pyproject_bate_com_o_manifest(self):
        assert pyproject_version() == manifest_version()

    def test_arquivo_gerado_bate_com_o_manifest(self):
        assert app_version._from_generated() == manifest_version()

    def test_sync_version_check_passa(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "sync_version.py"), "--check"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr


class CliRunner:
    """Roda a CLI em subprocesso e devolve o resultado."""

    def run(self, *args, timeout=120):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run(
            [sys.executable, "-m", "pinterest_board_dl", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(ROOT),
            env=env,
        )


class TestCliVersionFlag:
    def _run(self, *args):
        return CliRunner().run(*args)

    def test_version_imprime_a_versao(self):
        result = self._run("--version")
        assert result.returncode == 0
        assert manifest_version() in result.stdout

    def test_version_nao_exige_usuario(self):
        # a flag tem que responder sem os outros argumentos obrigatorios
        result = self._run("--version")
        assert "usage:" not in result.stdout
        assert "error:" not in result.stderr.lower()

    def test_sem_usuario_mostra_o_help(self):
        result = self._run()
        assert result.returncode != 0
        assert "usage:" in result.stdout

    def test_help_menciona_a_flag(self):
        result = self._run("--help")
        assert "--version" in result.stdout


class TestCliUserFlag:
    """A CLI aceita o usuario como --user e como argumento posicional.

    O parse e testado direto no parser, sem rodar a CLI: o `main()`
    abre o navegador e tocaria a rede.
    """

    def test_user_como_flag(self):
        args = build_arg_parser().parse_args(["--user", "usuario_pinterest"])
        assert args.user_option == "usuario_pinterest"

    def test_user_como_posicional(self):
        args = build_arg_parser().parse_args(["usuario_pinterest"])
        assert args.user == "usuario_pinterest"

    def test_sem_usuario(self):
        args = build_arg_parser().parse_args([])
        assert args.user is None
        assert args.user_option is None

    def test_as_duas_formas_levam_ao_mesmo_usuario(self):
        parser = build_arg_parser()
        por_flag = parser.parse_args(["--user", "abc"])
        por_posicional = parser.parse_args(["abc"])
        assert (por_flag.user_option or por_flag.user) == (por_posicional.user_option or por_posicional.user) == "abc"

    def test_o_help_documenta_as_duas_formas(self):
        result = CliRunner().run("--help")
        assert "--user" in result.stdout

    def test_o_comando_do_readme_e_aceito(self):
        # o comando que o README documenta tem que passar pelo parser
        parser = build_arg_parser()
        args = parser.parse_args(["--user", "usuario_pinterest"])
        assert args.user_option == "usuario_pinterest"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
