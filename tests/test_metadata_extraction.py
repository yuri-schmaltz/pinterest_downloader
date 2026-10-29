#!/usr/bin/env python3
"""Testes da extração de metadados de pins.

Ate aqui a extracao de metadados vivia dentro de um closure dentro de
`_collect_pin_links_with_browser`, que era impossivel de testar: o unico
jeito de exercitar o codigo era abrir um browser de verdade contra o
Pinterest -- o que a suite nao faz, por nao tocar a rede.

Depois do refactor a logica virou funcoes de nivel de modulo, e cada uma
pode ser testada com um payload na mao. E o que estes testes fazem.

O que eles cobrem:
  1. a conversao de um payload de pin em metadados normalizados
  2. a busca recursiva de pins dentro de uma resposta GraphQL
  3. a extracao da lista de pins de uma resposta `resource/...`
  4. o filtro de quais respostas de rede valem a pena abrir
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from pinterest_board_dl import (
    PINTEREST_BASE_URL,
    _collect_pin_metadata,
    _find_pins_in_graphql,
    _looks_like_pin,
    _pin_metadata_from_payload,
    _pins_from_resource_payload,
)


class FakeResponse:
    """Resposta de rede minima: url + json()."""

    def __init__(self, url, payload=None, raises=False):
        self.url = url
        self._payload = payload
        self._raises = raises

    def json(self):
        if self._raises:
            raise ValueError("nao e json")
        return self._payload


# ---------- 1. payload -> metadados ----------


class TestPinMetadataFromPayload:
    def test_formato_antigo_id_e_images_aninhado(self):
        meta = _pin_metadata_from_payload(
            {
                "id": "12345",
                "images": {"orig": {"url": "https://i.pinimg.com/originals/a.jpg"}},
                "title": "Decoração",
                "description": "desc",
            }
        )
        assert meta is not None
        assert meta["id"] == "12345"
        assert meta["url"] == f"{PINTEREST_BASE_URL}/pin/12345/"
        assert meta["image_url"] == "https://i.pinimg.com/originals/a.jpg"
        assert meta["title"] == "Decoração"
        assert meta["description"] == "desc"

    def test_formato_graphql_entityid_e_images_achatas(self):
        meta = _pin_metadata_from_payload(
            {
                "entityId": "999",
                "images_orig": {"url": "https://i.pinimg.com/originals/b.jpg"},
                "gridTitle": "Título do grid",
            }
        )
        assert meta is not None
        assert meta["id"] == "999"
        assert meta["image_url"] == "https://i.pinimg.com/originals/b.jpg"
        assert meta["title"] == "Título do grid"

    def test_sem_id_devolve_none(self):
        assert _pin_metadata_from_payload({"images": {"orig": {"url": "x.jpg"}}}) is None

    def test_id_vazio_no_campo_vazio(self):
        assert _pin_metadata_from_payload({"id": "", "images": {"orig": {"url": "x.jpg"}}}) is None

    def test_sem_imagem_devolve_none(self):
        assert _pin_metadata_from_payload({"id": "123", "images": {}}) is None

    def test_imagem_sem_url_devolve_none(self):
        assert _pin_metadata_from_payload({"id": "123", "images": {"orig": {}}}) is None

    def test_prefere_orig_sobre_736x(self):
        meta = _pin_metadata_from_payload(
            {
                "id": "1",
                "images": {
                    "orig": {"url": "orig.jpg"},
                    "736x": {"url": "736.jpg"},
                },
            }
        )
        assert meta is not None
        assert meta["image_url"] == "orig.jpg"

    def test_usa_736x_quando_nao_ha_orig(self):
        meta = _pin_metadata_from_payload({"id": "1", "images": {"736x": {"url": "736.jpg"}}})
        assert meta is not None
        assert meta["image_url"] == "736.jpg"

    def test_imagem_achata_tem_precedencia_sobre_aninhada(self):
        meta = _pin_metadata_from_payload(
            {
                "id": "1",
                "images_orig": {"url": "flat.jpg"},
                "images": {"orig": {"url": "nested.jpg"}},
            }
        )
        assert meta is not None
        assert meta["image_url"] == "flat.jpg"

    def test_titulo_vazio_aceita_grid_title(self):
        meta = _pin_metadata_from_payload({"id": "1", "images_orig": {"url": "x.jpg"}, "grid_title": "do grid_title"})
        assert meta is not None
        assert meta["title"] == "do grid_title"

    def test_descricao_ausente_vira_vazio(self):
        meta = _pin_metadata_from_payload({"id": "1", "images_orig": {"url": "x.jpg"}})
        assert meta is not None
        assert meta["description"] == ""


# ---------- 2. busca recursiva no GraphQL ----------


class TestFindPinsInGraphql:
    def test_acha_pin_no_nivel_topo(self):
        payload = {"entityId": "1", "images_orig": {"url": "x.jpg"}}
        found = _find_pins_in_graphql(payload)
        assert len(found) == 1
        assert found[0]["entityId"] == "1"

    def test_acha_pin_aninhado(self):
        payload = {"data": {"viewer": {"pins": [{"entityId": "1", "images_orig": {"url": "x.jpg"}}]}}}
        found = _find_pins_in_graphql(payload)
        assert len(found) == 1

    def test_acha_varios_pins(self):
        payload = {
            "data": {
                "pins": [
                    {"entityId": "1", "images_orig": {"url": "a.jpg"}},
                    {"entityId": "2", "images_orig": {"url": "b.jpg"}},
                ]
            }
        }
        found = _find_pins_in_graphql(payload)
        assert {p["entityId"] for p in found} == {"1", "2"}

    def test_lista_no_topo(self):
        found = _find_pins_in_graphql([{"entityId": "1", "images_orig": {"url": "x.jpg"}}])
        assert len(found) == 1

    def test_dict_sem_pin_devolve_vazio(self):
        assert _find_pins_in_graphql({"foo": "bar"}) == []

    def test_primitivas_devolve_vazio(self):
        assert _find_pins_in_graphql("texto") == []
        assert _find_pins_in_graphql(42) == []
        assert _find_pins_in_graphql(None) == []

    def test_nao_confunde_obj_que_so_tem_id(self):
        # tem id, mas nao tem imagem: nao e pin
        assert _find_pins_in_graphql({"id": "1", "title": "so um id"}) == []

    def test_encontra_pin_dentro_de_outro_dict(self):
        payload = {
            "data": {
                "node": {"id": "node-1", "title": "node"},
                "pins": [{"entityId": "77", "images_orig": {"url": "x.jpg"}}],
            }
        }
        found = _find_pins_in_graphql(payload)
        assert len(found) == 1
        assert found[0]["entityId"] == "77"


class TestLooksLikePin:
    def test_com_id_e_imagem(self):
        assert _looks_like_pin({"id": "1", "images_orig": {"url": "x"}}) is True

    def test_sem_id(self):
        assert _looks_like_pin({"images_orig": {"url": "x"}}) is False

    def test_sem_imagem(self):
        assert _looks_like_pin({"id": "1"}) is False

    def test_entityid_conta_como_id(self):
        assert _looks_like_pin({"entityId": "1", "images": {"orig": {"url": "x"}}}) is True

    def test_images_vazio_nao_conta_como_imagem(self):
        # o codigo original tambem rejeitava: um "images": {} nao diz nada
        # sobre qual imagem baixar
        assert _looks_like_pin({"entityId": "1", "images": {}}) is False


# ---------- 3. resposta resource/... ----------


class TestPinsFromResourcePayload:
    def test_resource_response_com_data(self):
        payload = {"resource_response": {"data": [{"id": "1"}, {"id": "2"}]}}
        pins = _pins_from_resource_payload(payload)
        assert [p["id"] for p in pins] == ["1", "2"]

    def test_data_no_topo(self):
        pins = _pins_from_resource_payload({"data": [{"id": "1"}]})
        assert len(pins) == 1

    def test_descarta_itens_que_nao_sao_dict(self):
        payload = {"resource_response": {"data": [{"id": "1"}, "lixo", None, 42]}}
        pins = _pins_from_resource_payload(payload)
        assert len(pins) == 1

    def test_resource_response_sem_data(self):
        assert _pins_from_resource_payload({"resource_response": {}}) == []

    def test_resource_response_que_nao_e_dict(self):
        assert _pins_from_resource_payload({"resource_response": "lixo"}) == []

    def test_data_que_nao_e_lista(self):
        assert _pins_from_resource_payload({"data": {"id": "1"}}) == []

    def test_sem_nenhum_dos_dois(self):
        assert _pins_from_resource_payload({"outro": []}) == []


# ---------- 4. filtro de respostas ----------


class TestCollectPinMetadata:
    def test_ignora_resposta_do_pinterest_que_nao_e_pin(self):
        resp = FakeResponse("https://www.pinterest.com/resource/OtherResource/get", {"data": []})
        assert _collect_pin_metadata(resp) == []

    def test_ignora_url_de_fora(self):
        resp = FakeResponse("https://exemplo.com/qualquer", {"data": [{"id": "1"}]})
        assert _collect_pin_metadata(resp) == []

    def test_le_resource_board_feed(self):
        resp = FakeResponse(
            "https://www.pinterest.com/resource/BoardFeedResource/get",
            {"resource_response": {"data": [{"id": "1", "images": {"orig": {"url": "x.jpg"}}}]}},
        )
        metas = _collect_pin_metadata(resp)
        assert len(metas) == 1
        assert metas[0]["id"] == "1"

    def test_le_resource_user_pins(self):
        resp = FakeResponse(
            "https://www.pinterest.com/resource/UserPinsResource/get",
            {"data": [{"id": "2", "images": {"orig": {"url": "y.jpg"}}}]},
        )
        assert len(_collect_pin_metadata(resp)) == 1

    def test_le_resource_board(self):
        resp = FakeResponse(
            "https://www.pinterest.com/resource/BoardResource/get",
            {"data": [{"id": "3", "images": {"orig": {"url": "z.jpg"}}}]},
        )
        assert len(_collect_pin_metadata(resp)) == 1

    def test_le_graphql(self):
        resp = FakeResponse(
            "https://www.pinterest.com/_/graphql/",
            {"data": {"pins": [{"entityId": "7", "images_orig": {"url": "g.jpg"}}]}},
        )
        metas = _collect_pin_metadata(resp)
        assert len(metas) == 1
        assert metas[0]["id"] == "7"

    def test_resposta_que_nao_e_json_nao_quebra(self):
        resp = FakeResponse("https://www.pinterest.com/resource/BoardFeedResource/get", raises=True)
        assert _collect_pin_metadata(resp) == []

    def test_json_que_nao_e_dict(self):
        resp = FakeResponse("https://www.pinterest.com/resource/BoardFeedResource/get", ["lista"])
        assert _collect_pin_metadata(resp) == []

    def test_pin_sem_imagem_e_ignorado(self):
        resp = FakeResponse(
            "https://www.pinterest.com/resource/BoardFeedResource/get",
            {"data": [{"id": "1"}, {"id": "2", "images": {"orig": {"url": "ok.jpg"}}}]},
        )
        metas = _collect_pin_metadata(resp)
        assert len(metas) == 1
        assert metas[0]["id"] == "2"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
