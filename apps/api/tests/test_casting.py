from pathlib import Path

from fastapi.testclient import TestClient
from yijing_ai.main import app
from yijing_ai.knowledge import (
    build_transition_reading,
    FREIZL_YIJING_ARCHIVE_PATH,
    get_hexagram,
    hexagram_seed_rows,
    import_freizl_yijing,
    load_retrieval_cases,
    seed_demo_evaluation,
    seed_hexagram_profiles,
    seed_hexagrams,
)
from yijing_liuyao import CoinSide, LineValue, cast, cast_from_coins, hexagram_catalog


def test_coin_toss_mapping() -> None:
    assert cast_from_coins([CoinSide.TAILS] * 3) is LineValue.OLD_YIN
    assert cast_from_coins([CoinSide.HEADS, CoinSide.TAILS, CoinSide.TAILS]) is LineValue.YOUNG_YANG
    assert cast_from_coins([CoinSide.HEADS, CoinSide.HEADS, CoinSide.TAILS]) is LineValue.YOUNG_YIN
    assert cast_from_coins([CoinSide.HEADS] * 3) is LineValue.OLD_YANG


def test_changing_lines_create_changed_hexagram() -> None:
    result = cast([6, 7, 7, 7, 7, 7])

    assert result.original.name == "天风姤"
    assert result.changed.name == "乾为天"
    assert result.moving_line_positions == (1,)


def test_hexagram_catalog_matches_casting_rules() -> None:
    catalog = hexagram_catalog()

    assert len(catalog) == 64
    assert catalog[0].name == "乾为天"
    assert catalog[0].binary_key == "111111"
    assert catalog[-1].name == "火水未济"
    assert len({entry.binary_key for entry in catalog}) == 64


def test_hexagram_seed_rows_cover_the_canonical_catalog() -> None:
    rows = hexagram_seed_rows()

    assert len(rows) == 64
    assert rows[0] == (1, "111111", "乾为天", "乾", "乾")
    assert rows[-1] == (64, "101010", "火水未济", "离", "坎")


def test_sqlite_knowledge_store_seeds_and_queries_a_hexagram(tmp_path: Path) -> None:
    database_path = tmp_path / "yijing.db"

    assert seed_hexagrams(database_path) == 64
    assert seed_demo_evaluation(database_path) == 24
    result = get_hexagram("111111", database_path)

    assert result == {
        "binary_key": "111111",
        "king_wen_no": 1,
        "name": "乾为天",
        "upper_trigram": "乾",
        "lower_trigram": "乾",
        "source_text_count": 0,
    }
    assert seed_hexagram_profiles(database_path) == 64


def test_archived_classical_corpus_imports_complete_moving_line_texts(tmp_path: Path) -> None:
    database_path = tmp_path / "yijing.db"

    imported = import_freizl_yijing(FREIZL_YIJING_ARCHIVE_PATH, database_path)
    result = build_transition_reading(cast([6, 7, 7, 7, 7, 7]), database_path)

    assert (imported.hexagram_count, imported.source_text_count) == (64, 448)
    assert result["classical_texts"]["original_gua_ci"]["body"].startswith("姤：")
    assert result["classical_texts"]["changed_gua_ci"]["body"].startswith("乾：")
    assert result["classical_texts"]["moving_lines"][0]["body"].startswith("初六：")


def test_retrieval_cases_are_complete_and_valid() -> None:
    cases_path = Path(__file__).resolve().parents[3] / "data" / "evaluation" / "retrieval_cases.json"
    cases = load_retrieval_cases(cases_path)

    assert len(cases) == 24
    assert cases[0].case_key == "career-start-resources"
    assert cases[0].expected_hexagram_keys == ("010100",)


def test_knowledge_hexagram_endpoint_returns_seeded_record() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/knowledge/hexagrams/010100")

    assert response.status_code == 200
    assert response.json()["name"] == "水雷屯"
    assert response.json()["source_text_count"] >= 0


def test_transition_reading_directly_describes_the_changed_hexagram(tmp_path: Path) -> None:
    result = build_transition_reading(cast([6, 7, 7, 7, 7, 7]), tmp_path / "yijing.db")

    assert result["original"]["name"] == "天风姤"
    assert result["changed"]["name"] == "乾为天"
    assert result["moving_line_positions"] == [1]
    assert "第1爻发动" in result["display"]
    assert result["provenance"] == "editorial_demo"


def test_transition_reading_endpoint_returns_direct_display() -> None:
    client = TestClient(app)
    response = client.post("/api/v1/knowledge/transition-readings", json={"lines": [6, 7, 7, 7, 7, 7]})

    assert response.status_code == 200
    assert response.json()["changed"]["name"] == "乾为天"
    assert "第1爻发动" in response.json()["display"]


def test_casting_endpoint_returns_server_calculated_result() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/castings",
        json={"question": "近期事业方向", "lines": [6, 7, 7, 7, 7, 7]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["original"]["name"] == "天风姤"
    assert payload["changed"]["name"] == "乾为天"
    assert payload["moving_line_positions"] == [1]