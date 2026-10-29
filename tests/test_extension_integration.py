#!/usr/bin/env python3
"""Teste de integracao da extensao: os scripts reais, carregados numa
pagina real, num browser real.

Cobre o que os testes em Node nao cobrem -- que os scripts da extensao
carregam na ordem certa e que o content.js funciona depois do refactor
que extraiu as funcoes de URL para lib/pin_utils.js.

A ordem de carregamento vem do manifest:
    lib/i18n.js -> lib/pin_utils.js -> content.js

Se essa ordem quebrar, a extensao deixa de funcionar no navegador --
e nada mais denuncia isso.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

ROOT = Path(__file__).parent.parent
EXT = ROOT / "extension"
PAGE_FIXTURE = Path(__file__).parent / "fixtures" / "pinterest_page.html"


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api", reason="playwright nao instalado")
    try:
        with pw.sync_playwright() as p:
            try:
                b = p.chromium.launch(headless=True)
            except Exception as exc:
                pytest.skip(f"Chromium indisponivel (rode 'playwright install chromium'): {exc}")
            yield b
            b.close()
    except Exception as exc:
        pytest.skip(f"playwright indisponivel: {exc}")


@pytest.fixture(scope="module")
def manifest():
    return json.loads((EXT / "manifest.json").read_text())


@pytest.fixture
def page(browser, manifest):
    """Pagina com os scripts da extensao carregados na ordem do manifest."""
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(PAGE_FIXTURE.resolve().as_uri(), wait_until="load")

    for script in manifest["content_scripts"][0]["js"]:
        page.add_script_tag(path=str(EXT / script))

    yield page
    ctx.close()


class TestManifestContract:
    def test_manifest_is_valid_json(self, manifest):
        assert manifest["manifest_version"] == 3

    def test_every_referenced_script_exists(self, manifest):
        referenced = []
        for entry in manifest.get("content_scripts", []):
            referenced += entry.get("js", [])
        referenced.append(manifest["background"]["service_worker"])
        referenced.append(manifest["action"]["default_popup"])

        for rel in referenced:
            assert (EXT / rel).exists(), f"manifest referencia '{rel}', que nao existe"

    def test_i18n_is_loaded_before_content(self, manifest):
        """content.js le window.__pbdI18n no load -- se o i18n vier depois,
        a extensao perde as traducoes."""
        scripts = manifest["content_scripts"][0]["js"]
        assert "lib/i18n.js" in scripts
        assert scripts.index("lib/i18n.js") < scripts.index("content.js")

    def test_pin_utils_is_loaded_before_content(self, manifest):
        """content.js le window.__pbdPinUtils no load."""
        scripts = manifest["content_scripts"][0]["js"]
        assert "lib/pin_utils.js" in scripts
        assert scripts.index("lib/pin_utils.js") < scripts.index("content.js")


class TestScriptsLoad:
    def test_i18n_exposes_its_api(self, page):
        assert page.evaluate("() => typeof window.__pbdI18n") == "object"
        assert page.evaluate("() => typeof window.__pbdI18n.t") == "function"

    def test_pin_utils_exposes_its_api(self, page):
        assert page.evaluate("() => typeof window.__pbdPinUtils") == "object"
        assert page.evaluate("() => typeof window.__pbdPinUtils.getOriginalImageUrl") == "function"

    def test_content_script_runs_without_errors(self, page):
        """Se o content.js explodesse, a barra flutuante nao apareceria."""
        assert page.evaluate("() => !!document.getElementById('pinterest-pro-toolbar')")

    def test_toolbar_is_translated(self, page):
        """A barra usa o i18n -- com o texto traduzido, nao a chave crua."""
        label = page.evaluate(
            "() => { const t = document.getElementById('pinterest-pro-toolbar');"
            "return t ? (t.getAttribute('aria-label') || t.textContent || '') : ''; }"
        )
        assert label
        assert label != "toolbar_aria", "a barra caiu no fallback de chave crua"

    def test_no_console_errors(self, page):
        """Um erro de sintaxe no content.js aparece no console."""
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.reload()
        page.add_script_tag(path=str(EXT / "lib" / "i18n.js"))
        page.add_script_tag(path=str(EXT / "lib" / "pin_utils.js"))
        page.add_script_tag(path=str(EXT / "content.js"))
        page.wait_for_timeout(300)
        assert not errors, f"erros de JS: {errors}"


class TestHarvesting:
    def test_counts_only_the_pin_images(self, page):
        """A fixture tem 4 imagens de pin (o mesmo pin em duas resolucoes) e
        3 imagens que nao sao pins (avatar, icone, host externo).

        A contagem e de IMAGENS, nao de pins distintos -- e a deduplicacao
        fica por conta do fingerprint, testado abaixo."""
        count = page.evaluate("() => window.__pbdPinUtils.countHarvestableImages()")
        assert count == 4, f"esperava 4 imagens de pin, contou {count}"

    def test_fingerprint_deduplicates_the_same_pin(self, page):
        """As duas resolucoes do mesmo pin viram a mesma URL original --
        entao o fingerprint tem que ter uma entrada so."""
        fingerprint = page.evaluate("() => window.__pbdPinUtils.pinFingerprint()")
        entries = [e for e in fingerprint.split("|") if e]
        assert len(entries) == 3, f"esperava 3 entradas unicas, veio {len(entries)}: {entries}"

    def test_every_entry_is_the_original_resolution(self, page):
        fingerprint = page.evaluate("() => window.__pbdPinUtils.pinFingerprint()")
        for entry in fingerprint.split("|"):
            if entry:
                assert "/originals/" in entry, f"entrada nao foi normalizada: {entry}"

    def test_no_avatar_or_external_image_leaks_in(self, page):
        fingerprint = page.evaluate("() => window.__pbdPinUtils.pinFingerprint()")
        assert "user.jpg" not in fingerprint
        assert "favicon" not in fingerprint
        assert "example.com" not in fingerprint


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
