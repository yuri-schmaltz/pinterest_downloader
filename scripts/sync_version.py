#!/usr/bin/env python3
"""Mantem a versao do projeto em um so lugar.

A versao aparecia em tres lugares independentes:
  - pyproject.toml          (pacote Python)
  - extension/manifest.json (extensao do navegador)
  - a tag do git            (release)

Qualquer um deles divergindo produz um artefato com versao errada -- foi o
que aconteceu com a v2.0.1, cujos assets se chamavam v2.0.0.

A fonte da verdade e extension/manifest.json:
  - e o que o build_release.sh le para nomear os artefatos
  - tem que ser uma versao valida de Chrome (ate 4 numeros, cada um ate 65535)
  - a versao que o usuario ve na loja de extensoes

Duas outras copias sao DERIVADAS e nunca editadas a mao:
  - pyproject.toml   (a versao do pacote Python)
  - src/_version.py  (a versao que o app mostra em --version)

Por que o app nao pergunta pro pacote instalado: num `pip install -e .`
a metadata fica congelada na instalacao, entao apos um bump de versao ela
continua reportando a versao antiga. Como o app e congelado num AppImage
sem metadata nenhuma, o caminho confiavel e um arquivo gerado.

Uso:
    python scripts/sync_version.py          # sincroniza as copias derivadas
    python scripts/sync_version.py --check  # so verifica (exit 1 se divergir)
    python scripts/sync_version.py --tag    # verifica tambem a tag do git
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "extension" / "manifest.json"
PYPROJECT = ROOT / "pyproject.toml"
GENERATED = ROOT / "src" / "_version.py"

# O arquivo gerado. O cabecalho avisa que ele e gerado: um dev que editar
# a mao vai ter o trabalho sobrescrito no proximo sync.
GENERATED_TEMPLATE = """\
# GERADO por scripts/sync_version.py -- nao editar a mao.
# A fonte da verdade e extension/manifest.json.
__version__ = "{version}"
"""

# Regra do Chrome: 1 a 4 numeros separados por ponto, cada um de 0 a 65535.
CHROME_VERSION_RE = re.compile(r"^\d{1,5}(\.\d{1,5}){0,3}$")


def read_manifest_version() -> str:
    import json

    return json.loads(MANIFEST.read_text())["version"]


def read_pyproject_version() -> str:
    """Le a versao do pyproject sem depender de tomllib (Python 3.10 nao tem
    tomllib; e a 3.11 tem, mas nem todo mundo roda 3.11)."""
    text = PYPROJECT.read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit(f"ERROR: nao achei 'version =' em {PYPROJECT}")
    return match.group(1)


def write_pyproject_version(version: str) -> bool:
    """Atualiza a versao no pyproject. Devolve True se mudou algo."""
    text = PYPROJECT.read_text()
    new_text, count = re.subn(
        r'^(version\s*=\s*)"[^"]+"',
        lambda m: f'{m.group(1)}"{version}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if count == 0:
        raise SystemExit(f"ERROR: nao achei 'version =' em {PYPROJECT}")
    if new_text != text:
        PYPROJECT.write_text(new_text)
        return True
    return False


def read_generated_version() -> str | None:
    """Versao no arquivo gerado, ou None se ele ainda nao existe."""
    if not GENERATED.exists():
        return None
    text = GENERATED.read_text()
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else None


def write_generated_version(version: str) -> bool:
    """Regenera src/_version.py. Devolve True se mudou algo."""
    content = GENERATED_TEMPLATE.format(version=version)
    if GENERATED.exists() and GENERATED.read_text() == content:
        return False
    GENERATED.parent.mkdir(parents=True, exist_ok=True)
    GENERATED.write_text(content)
    return True


def current_git_tag() -> str | None:
    """Tag do HEAD, se houver."""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--exact-match"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="so verifica, nao escreve")
    parser.add_argument("--tag", action="store_true", help="verifica tambem a tag do HEAD")
    args = parser.parse_args()

    manifest_version = read_manifest_version()
    pyproject_version = read_pyproject_version()

    if not CHROME_VERSION_RE.match(manifest_version):
        print(
            f"ERROR: '{manifest_version}' nao e uma versao valida para o Chrome.",
            file=sys.stderr,
        )
        return 1

    ok = True

    # pyproject.toml
    if manifest_version != pyproject_version:
        if args.check:
            ok = False
            print(f"DIVERGENCIA: manifest={manifest_version} pyproject={pyproject_version}")
        else:
            write_pyproject_version(manifest_version)
            print(f"CORRIGIDO: pyproject estava em {pyproject_version}, agora {manifest_version}")
    else:
        print(f"OK: manifest e pyproject estao em {manifest_version}")

    # src/_version.py -- o que o app mostra em --version
    generated_version = read_generated_version()
    if generated_version != manifest_version:
        if args.check:
            ok = False
            print(f"DIVERGENCIA: manifest={manifest_version} src/_version.py={generated_version}")
            print("  (use sem --check para sincronizar)", file=sys.stderr)
        else:
            write_generated_version(manifest_version)
            print(f"CORRIGIDO: src/_version.py estava em {generated_version}, agora {manifest_version}")
    else:
        print(f"OK: src/_version.py esta em {manifest_version}")

    if args.tag:
        tag = current_git_tag()
        if tag is None:
            print("OK: o HEAD nao tem tag (branch normal)")
        elif tag.lstrip("v") == manifest_version:
            print(f"OK: a tag {tag} bate com a versao")
        else:
            ok = False
            print(f"DIVERGENCIA: a tag do HEAD e {tag}, mas a versao e {manifest_version}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
