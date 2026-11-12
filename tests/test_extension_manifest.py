#!/usr/bin/env python3
"""O manifesto precisa carregar no Chrome e no Firefox.

Firefox MV3 nao suporta `background.service_worker` (Firefox bug 1573659) e
o Chrome recusa carregar uma extensao MV3 que tenha `background.scripts`
antes da versao 121. A combinacao cross-browser e declarar os dois: o Chrome
usa o service worker e ignora o `scripts`, o Firefox roda o script como event
page.

O XPI publicado antes desta regra carregava no Chrome e nao tinha background
no Firefox: a extensao instalava e nao coletava nada.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

ROOT = Path(__file__).parent.parent
MANIFEST = ROOT / "extension" / "manifest.json"


def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_o_manifest_declara_o_background_dos_dois_lados():
    background = manifest().get("background", {})
    assert background.get("service_worker") == "background.js", "o Chrome precisa do service worker"
    assert background.get("scripts") == ["background.js"], "o Firefox precisa do script como event page"


def test_o_requisito_de_versao_do_chrome_e_declarado():
    # O Chrome so ignora o "scripts" a partir da versao 121; antes disso ele
    # recusa carregar a extensao.
    minimum = manifest().get("minimum_chrome_version", "")
    assert minimum, "a extensao carrega scripts de background que o Chrome antigo recusa"
    assert int(minimum.split(".")[0]) >= 121, f"minimum_chrome_version {minimum} e anterior a 121"


def test_o_id_do_addon_do_firefox_existe():
    # O Firefox Add-ons exige um id explicito para aceitar o pacote.
    gecko = manifest().get("browser_specific_settings", {}).get("gecko", {})
    assert gecko.get("id"), "o Firefox Add-ons exige browser_specific_settings.gecko.id"
    assert "@" in gecko["id"], "o id do addon precisa ter a forma de um email"


def test_a_declaracao_de_coleta_de_dados_do_firefox_existe():
    # O Firefox Add-ons exige a declaracao desde o Firefox 140/142, e o piso
    # de versao precisa acompanhar a chave.
    gecko = manifest().get("browser_specific_settings", {}).get("gecko", {})
    collection = gecko.get("data_collection_permissions", {})
    assert collection.get("required") == ["none"], "a extensao nao envia dados a nenhum servidor, entao declara none"
    floor = gecko.get("strict_min_version", "0")
    major = int(floor.split(".")[0])
    assert major >= 142, (
        f"strict_min_version {floor} e anterior ao Firefox 142, que e a versao "
        "que suporta data_collection_permissions"
    )


def test_o_background_referenciado_existe_no_disco():
    ext = ROOT / "extension"
    background = manifest().get("background", {})
    referenced = [background.get("service_worker", "")] + background.get("scripts", [])
    for path in filter(None, referenced):
        assert (ext / path).is_file(), f"extension/{path} nao existe"


def test_o_manifest_continua_com_a_versao_unica_do_projeto():
    # O manifest e a fonte da verdade da versao; o sync_version.py deriva
    # as demais copias a partir dele.
    data = manifest()
    assert data["manifest_version"] == 3
    assert data["version"] == "2.0.5"
    assert data["default_locale"] == "en"
    for locale in ("en", "es", "pt_BR"):
        messages = ROOT / "extension" / "_locales" / locale / "messages.json"
        assert messages.is_file(), f"falta o locale {locale}"
