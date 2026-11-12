#!/usr/bin/env python3
"""O cache de pins precisa ter versao e idade, e as duas CLIs precisam
entender o mesmo diretorio.

O mapa continua em JSON simples, que e o que a CLI Rust le. A versao e a
idade ficam num arquivo ao lado, para que os dois tipos compartilhem o
diretorio sem deixar de se entender.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pinterest_board_dl
from pinterest_board_dl import (
    CACHE_META_FILE,
    CACHE_VERSION,
    load_pin_cache,
    save_pin_cache,
)

PIN = "https://www.pinterest.com/pin/1/"


def test_o_mapa_continua_sendo_um_objeto_simples(tmp_path):
    save_pin_cache({PIN: "http://img/1.jpg"}, str(tmp_path))
    raw = (tmp_path / ".pinterest_cache.json").read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert isinstance(parsed, dict), "o mapa precisa continuar um objeto simples"
    assert parsed[PIN] == "http://img/1.jpg"


def test_a_versao_e_a_idade_viam_no_arquivo_ao_lado(tmp_path):
    save_pin_cache({PIN: "http://img/1.jpg"}, str(tmp_path))
    meta = json.loads((tmp_path / CACHE_META_FILE).read_text(encoding="utf-8"))
    assert meta["version"] == CACHE_VERSION
    assert abs(meta["written_at"] - int(time.time())) < 120


def test_um_cache_vencido_nao_e_usado(tmp_path):
    save_pin_cache({PIN: "http://img/1.jpg"}, str(tmp_path))
    meta_path = tmp_path / CACHE_META_FILE
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["written_at"] = int(time.time()) - 40 * 86400
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    assert load_pin_cache(str(tmp_path), ttl_days=30) == {}
    # O arquivo continua lá: a outra ferramenta pode ainda lê-lo.
    assert (tmp_path / ".pinterest_cache.json").is_file()


def test_um_cache_dentro_do_prazo_e_usado(tmp_path):
    save_pin_cache({PIN: "http://img/1.jpg"}, str(tmp_path))
    assert load_pin_cache(str(tmp_path), ttl_days=30) == {PIN: "http://img/1.jpg"}


def test_um_cache_sem_metadados_e_aceito(tmp_path):
    # A CLI Rust escreveu o mapa antes do arquivo ao lado existir. As
    # entradas valem a pena: podem ter sido escritas agora pela outra
    # ferramenta.
    (tmp_path / ".pinterest_cache.json").write_text(json.dumps({PIN: "http://img/1.jpg"}))
    assert load_pin_cache(str(tmp_path), ttl_days=1) == {PIN: "http://img/1.jpg"}


def test_um_cache_corrompido_nao_quebra_a_execucao(tmp_path):
    (tmp_path / ".pinterest_cache.json").write_text("isto nao e json")
    assert load_pin_cache(str(tmp_path)) == {}


def test_um_zero_de_dias_nunca_expira(tmp_path):
    save_pin_cache({PIN: "http://img/1.jpg"}, str(tmp_path))
    meta_path = tmp_path / CACHE_META_FILE
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["written_at"] = 1
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    assert load_pin_cache(str(tmp_path), ttl_days=0) == {PIN: "http://img/1.jpg"}


def test_a_opcao_carrega_o_limite_padrao():
    assert pinterest_board_dl.DownloadOptions().cache_ttl_days == 30
