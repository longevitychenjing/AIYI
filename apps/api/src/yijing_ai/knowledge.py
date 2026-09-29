import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import sqlite3
from typing import Iterator
from urllib.request import urlopen

from yijing_liuyao import Casting, hexagram_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "knowledge" / "yijing.db"
DEMO_CASES_PATH = PROJECT_ROOT / "data" / "evaluation" / "retrieval_cases.json"
FREIZL_YIJING_REVISION = "018ce866f7115cd294a34fd19bd675953d2bdd1c"
FREIZL_YIJING_SOURCE_URL = (
    "https://raw.githubusercontent.com/freizl/yijing/"
    f"{FREIZL_YIJING_REVISION}/zh-CN/64gua.json"
)
FREIZL_YIJING_ARCHIVE_PATH = PROJECT_ROOT / "data" / "sources" / "freizl-yijing" / "64gua.json"
FREIZL_YIJING_EDITION_ID = f"freizl-yijing-64gua-{FREIZL_YIJING_REVISION[:12]}"

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS hexagrams (
    binary_key TEXT PRIMARY KEY CHECK (length(binary_key) = 6 AND binary_key NOT GLOB '*[^01]*'),
    king_wen_no INTEGER NOT NULL UNIQUE CHECK (king_wen_no BETWEEN 1 AND 64),
    name TEXT NOT NULL UNIQUE,
    upper_trigram TEXT NOT NULL,
    lower_trigram TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS editions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    edition_note TEXT NOT NULL,
    license_basis TEXT NOT NULL,
    source_url TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    content_sha256 TEXT NOT NULL UNIQUE CHECK (length(content_sha256) = 64)
);

CREATE TABLE IF NOT EXISTS source_texts (
    id TEXT PRIMARY KEY,
    edition_id TEXT NOT NULL REFERENCES editions(id),
    hexagram_key TEXT NOT NULL REFERENCES hexagrams(binary_key),
    line_position INTEGER CHECK (line_position BETWEEN 1 AND 6),
    text_kind TEXT NOT NULL CHECK (text_kind IN ('gua_ci', 'yao_ci', 'tuan', 'da_xiang', 'xiao_xiang', 'commentary')),
    body TEXT NOT NULL CHECK (length(trim(body)) > 0),
    locator TEXT NOT NULL CHECK (length(trim(locator)) > 0),
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    CHECK ((text_kind = 'yao_ci') = (line_position IS NOT NULL)),
    UNIQUE (edition_id, hexagram_key, text_kind, line_position)
);

CREATE TABLE IF NOT EXISTS hexagram_profiles (
    hexagram_key TEXT PRIMARY KEY REFERENCES hexagrams(binary_key),
    overview TEXT NOT NULL CHECK (length(trim(overview)) > 0),
    change_focus TEXT NOT NULL CHECK (length(trim(change_focus)) > 0),
    provenance TEXT NOT NULL CHECK (provenance IN ('editorial_demo', 'verified_source'))
);

CREATE TABLE IF NOT EXISTS semantic_codes (
    code TEXT PRIMARY KEY,
    dimension TEXT NOT NULL CHECK (dimension IN ('domain', 'phase', 'concern', 'stance')),
    label TEXT NOT NULL,
    definition TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS text_semantic_codes (
    source_text_id TEXT NOT NULL REFERENCES source_texts(id) ON DELETE CASCADE,
    semantic_code TEXT NOT NULL REFERENCES semantic_codes(code),
    provenance TEXT NOT NULL CHECK (provenance IN ('editor', 'model_reviewed')),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    annotation_note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (source_text_id, semantic_code)
);

CREATE TABLE IF NOT EXISTS retrieval_cases (
    case_key TEXT PRIMARY KEY,
    query TEXT NOT NULL CHECK (length(trim(query)) > 0),
    expected_codes TEXT NOT NULL,
    expected_hexagram_keys TEXT NOT NULL,
    must_not_return_hexagram_keys TEXT NOT NULL,
    rationale TEXT NOT NULL
);
"""

SEMANTIC_CODES = (
    ("domain.career", "domain", "事业", "与工作、组织、职业发展有关的问题。"),
    ("domain.relationship", "domain", "关系", "与亲密关系、家庭或协作关系有关的问题。"),
    ("domain.study", "domain", "学习", "与学习、训练、知识理解有关的问题。"),
    ("domain.decision", "domain", "决策", "与方案选择、取舍或判断有关的问题。"),
    ("phase.beginning", "phase", "起始", "处于刚开始、基础尚未稳固的阶段。"),
    ("phase.progressing", "phase", "推进", "正在展开、协作或执行的阶段。"),
    ("phase.blocked", "phase", "阻滞", "遭遇资源、沟通或环境阻塞的阶段。"),
    ("phase.transition", "phase", "转变", "正在结束旧状态或进入新状态的阶段。"),
    ("concern.opportunity", "concern", "机会", "关注可利用的机会、成长空间或时机。"),
    ("concern.risk", "concern", "风险", "关注不确定性、准备程度或潜在损失。"),
    ("concern.conflict", "concern", "冲突", "关注分歧、边界、争执或对抗。"),
    ("concern.cooperation", "concern", "协作", "关注配合、支持、互信或共同推进。"),
    ("stance.act", "stance", "行动", "希望获得下一步行动的参考。"),
    ("stance.wait", "stance", "等待", "需要判断是否等待、准备或观察。"),
    ("stance.learn", "stance", "学习", "需要求教、理解或补足基础。"),
    ("stance.review", "stance", "复盘", "需要回顾、修正或重新判断。"),
)

HEXAGRAM_PROFILE_COPY = {
    "乾为天": ("主动承担、持续精进，并以自我约束保持方向。", "把注意力放在主动推进与校正自身尺度。"),
    "坤为地": ("以承载和配合创造空间，重视回应现实条件。", "把注意力放在支持协作与稳住基础。"),
    "水雷屯": ("起始阶段困难交织，先整理资源与次序。", "把注意力放在建立秩序和补足起步条件。"),
    "山水蒙": ("面对未知时承认不足，通过求教建立理解。", "把注意力放在学习、提问与厘清方法。"),
    "水天需": ("条件尚未齐备，准备与等待同样重要。", "把注意力放在准备充分后判断时机。"),
    "天水讼": ("分歧已经显现，应先厘清边界与规则。", "把注意力放在止争、沟通和重新界定责任。"),
    "地水师": ("行动需要组织、纪律和可执行的分工。", "把注意力放在统筹资源与明确责任。"),
    "水地比": ("建立连接与信任，选择可靠的协作关系。", "把注意力放在互信、归属和持续配合。"),
    "风天小畜": ("以小步积累力量，不急于一次完成。", "把注意力放在节制推进与保存余力。"),
    "天泽履": ("行动有边界，保持谨慎和对他人的尊重。", "把注意力放在按规则行事与控制风险。"),
    "地天泰": ("内外较为通达，适合协调资源与交流。", "把注意力放在扩大协作并维持平衡。"),
    "天地否": ("沟通受阻、内外隔绝，应守住核心并重新连接。", "把注意力放在减少消耗与检视阻塞来源。"),
    "天火同人": ("围绕共同目标公开协作，凝聚不同成员。", "把注意力放在共享目标和透明沟通。"),
    "火天大有": ("资源与机会增多，更需要妥善分配责任。", "把注意力放在管理拥有之物并回馈关系。"),
    "地山谦": ("以谦抑平衡得失，在成果中保持分寸。", "把注意力放在留出空间与避免自满。"),
    "雷地豫": ("热情和动员正在形成，也要防止松懈。", "把注意力放在把积极性转成可持续行动。"),
    "泽雷随": ("顺应环境与关系变化，同时保有自主判断。", "把注意力放在辨别可随与不可随的界线。"),
    "山风蛊": ("旧有积弊需要被看见和修正。", "把注意力放在清理问题根源与重建秩序。"),
    "地泽临": ("接近机会与责任，宜以耐心回应他人。", "把注意力放在及时靠近并承担相应责任。"),
    "风地观": ("先拉开距离观察形势，避免仓促介入。", "把注意力放在收集信息与调整视角。"),
    "火雷噬嗑": ("阻碍需要被处理，规则与执行不可含混。", "把注意力放在解决卡点和明确后果。"),
    "山火贲": ("重视表达与形式，但不让修饰遮蔽实质。", "把注意力放在让形式服务于真实内容。"),
    "山地剥": ("结构正在削弱，优先保存根基与关键资源。", "把注意力放在收缩、修补和避免额外损耗。"),
    "地雷复": ("回到根本，适合重新开始和校准方向。", "把注意力放在恢复节奏与落实最小行动。"),
    "天雷无妄": ("不妄为，以事实和本分作为行动依据。", "把注意力放在去除侥幸并保持诚实。"),
    "山天大畜": ("积蓄力量与资源，必要时约束过快行动。", "把注意力放在训练、储备和等待成熟。"),
    "山雷颐": ("关注输入、供养与长期支持系统。", "把注意力放在改善信息、资源和关系的供给。"),
    "泽风大过": ("承担过重，已有结构需要重新支撑。", "把注意力放在减压、分担和重设支点。"),
    "坎为水": ("风险与困难反复出现，需要谨慎穿越。", "把注意力放在识别风险、保持节奏和寻求支持。"),
    "离为火": ("需要清晰辨别并找到可靠的依托。", "把注意力放在澄清事实与连接可信资源。"),
    "泽山咸": ("感应与吸引发生，关系中仍需保持分寸。", "把注意力放在真诚回应与尊重边界。"),
    "雷风恒": ("长期坚持比短期热度更重要。", "把注意力放在建立稳定做法并适时修正。"),
    "天山遁": ("适时退让可保存空间与选择权。", "把注意力放在离开无效消耗并守住底线。"),
    "雷天大壮": ("力量正在增强，避免以强硬代替判断。", "把注意力放在有力而不过度地推进。"),
    "火地晋": ("进展和可见度提升，适合稳步展示成果。", "把注意力放在开放交流并延续增长。"),
    "地火明夷": ("核心价值受到压制，宜先保护自己与关键事物。", "把注意力放在低调保存力量和识别环境。"),
    "风火家人": ("内部角色与责任需要清楚，关系靠日常维护。", "把注意力放在明确分工与稳定沟通。"),
    "火泽睽": ("差异并存，先寻找有限而真实的共识。", "把注意力放在尊重不同并处理具体分歧。"),
    "水山蹇": ("路径不易通行，适合放慢并借助外部支持。", "把注意力放在绕开障碍和寻求协助。"),
    "雷水解": ("压力开始松动，宜处理遗留问题而非重新加压。", "把注意力放在释放负担与完成善后。"),
    "山泽损": ("减少无效投入，把资源集中于要点。", "把注意力放在取舍、节约和保留关键。"),
    "风雷益": ("适度增加投入能带来共同收益。", "把注意力放在互惠、支持和扩大有效资源。"),
    "泽天夬": ("需要作出清楚决断，也要公开说明依据。", "把注意力放在果断处理并避免情绪化对抗。"),
    "天风姤": ("新因素意外出现，先辨别其边界与影响。", "把注意力放在审慎接触和保持主动。"),
    "泽地萃": ("人事与资源正在汇聚，需要共同秩序。", "把注意力放在凝聚共识与安排协作。"),
    "地风升": ("以持续积累实现逐步上升，根基不可忽视。", "把注意力放在循序推进和巩固基础。"),
    "泽水困": ("资源或表达受限，需在有限条件中寻找空间。", "把注意力放在节省力量、沟通支持和守住方向。"),
    "水风井": ("维护共同资源与基础设施，惠及长期关系。", "把注意力放在修复供给系统与共享价值。"),
    "泽火革": ("旧做法不再适用，变革需要时机与共识。", "把注意力放在明确变更理由并有序转换。"),
    "火风鼎": ("资源正在被转化，可形成新的成果与结构。", "把注意力放在整合能力并提升成果质量。"),
    "震为雷": ("突发变化带来震动，先稳定再回应。", "把注意力放在应急、复位和避免恐慌扩散。"),
    "艮为山": ("适时停止与观照，避免在不宜动时强行推进。", "把注意力放在设定界限、暂停和沉淀。"),
    "风山渐": ("循序渐进比快速跳跃更可靠。", "把注意力放在耐心安排和逐步建立信任。"),
    "雷泽归妹": ("关系或位置未必对等，需要明确承诺和责任。", "把注意力放在辨清角色并避免仓促绑定。"),
    "雷火丰": ("资源与声势处于高点，更应防止过度扩张。", "把注意力放在管理高峰、保持清醒和分配资源。"),
    "火山旅": ("环境暂时或位置不稳，适合轻装适应。", "把注意力放在保持弹性并尊重所处环境。"),
    "巽为风": ("以柔和而持续的方式渗透沟通。", "把注意力放在循序影响和反复确认。"),
    "兑为泽": ("交流可以带来舒展，但需避免轻率承诺。", "把注意力放在坦诚表达与兑现约定。"),
    "风水涣": ("人心或资源涣散，需要重新凝聚。", "把注意力放在解除隔阂并重建共同方向。"),
    "水泽节": ("节制与范围带来秩序，限制应当合理。", "把注意力放在设定可执行的界线与节奏。"),
    "风泽中孚": ("真诚是关系与合作的基础。", "把注意力放在言行一致和建立信任。"),
    "雷山小过": ("小事可积极处理，大动作则宜谨慎。", "把注意力放在修正细节并避免过度承诺。"),
    "水火既济": ("阶段性完成后仍需防范松懈与失衡。", "把注意力放在交接、维护和持续检查。"),
    "火水未济": ("事情尚未完成，适合检查次序并继续准备。", "把注意力放在补齐条件和耐心完成最后步骤。"),
}


@dataclass(frozen=True)
class RetrievalCase:
    case_key: str
    query: str
    expected_codes: tuple[str, ...]
    expected_hexagram_keys: tuple[str, ...]
    must_not_return_hexagram_keys: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class ClassicalTextImport:
    source_path: Path
    source_sha256: str
    hexagram_count: int
    source_text_count: int


def database_path() -> Path:
    return Path(os.getenv("YIJING_KNOWLEDGE_DB", DEFAULT_DATABASE_PATH))


@contextmanager
def _connect(path: Path) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(path: Path | None = None) -> Path:
    target_path = path or database_path()
    with _connect(target_path) as connection:
        connection.executescript(SCHEMA)
    return target_path


def hexagram_seed_rows() -> tuple[tuple[int, str, str, str, str], ...]:
    return tuple(
        (entry.king_wen_no, entry.binary_key, entry.name, entry.upper_trigram, entry.lower_trigram)
        for entry in hexagram_catalog()
    )


def load_retrieval_cases(path: Path = DEMO_CASES_PATH) -> tuple[RetrievalCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    code_set = {code for code, _, _, _ in SEMANTIC_CODES}
    hexagram_keys = {entry.binary_key for entry in hexagram_catalog()}
    cases: list[RetrievalCase] = []
    for item in payload["cases"]:
        case = RetrievalCase(
            case_key=str(item["case_key"]),
            query=str(item["query"]),
            expected_codes=tuple(str(code) for code in item["expected_codes"]),
            expected_hexagram_keys=tuple(str(key) for key in item["expected_hexagram_keys"]),
            must_not_return_hexagram_keys=tuple(str(key) for key in item.get("must_not_return_hexagram_keys", [])),
            rationale=str(item["rationale"]),
        )
        if not case.case_key or not case.query or not case.rationale:
            raise ValueError("Every retrieval case requires a key, query, and rationale.")
        if len(case.expected_codes) != 4 or not set(case.expected_codes) <= code_set:
            raise ValueError(f"Retrieval case {case.case_key} has invalid semantic codes.")
        if not case.expected_hexagram_keys or not set(case.expected_hexagram_keys) <= hexagram_keys:
            raise ValueError(f"Retrieval case {case.case_key} has invalid expected hexagrams.")
        if not set(case.must_not_return_hexagram_keys) <= hexagram_keys:
            raise ValueError(f"Retrieval case {case.case_key} has invalid excluded hexagrams.")
        cases.append(case)
    if len({case.case_key for case in cases}) != len(cases):
        raise ValueError("Retrieval case keys must be unique.")
    return tuple(cases)


def seed_hexagrams(path: Path | None = None) -> int:
    target_path = initialize_database(path)
    with _connect(target_path) as connection:
        connection.executemany(
            """
            INSERT INTO hexagrams (king_wen_no, binary_key, name, upper_trigram, lower_trigram)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (binary_key) DO UPDATE SET
                king_wen_no = excluded.king_wen_no,
                name = excluded.name,
                upper_trigram = excluded.upper_trigram,
                lower_trigram = excluded.lower_trigram
            """,
            hexagram_seed_rows(),
        )
    return 64


def seed_hexagram_profiles(path: Path | None = None) -> int:
    target_path = path or database_path()
    seed_hexagrams(target_path)
    keys_by_name = {entry.name: entry.binary_key for entry in hexagram_catalog()}
    if set(keys_by_name) != set(HEXAGRAM_PROFILE_COPY):
        raise RuntimeError("The direct profile catalog does not cover every hexagram.")
    with _connect(target_path) as connection:
        connection.executemany(
            """
            INSERT INTO hexagram_profiles (hexagram_key, overview, change_focus, provenance)
            VALUES (?, ?, ?, 'editorial_demo')
            ON CONFLICT (hexagram_key) DO UPDATE SET
                overview = excluded.overview,
                change_focus = excluded.change_focus,
                provenance = excluded.provenance
            """,
            [
                (keys_by_name[name], overview, change_focus)
                for name, (overview, change_focus) in HEXAGRAM_PROFILE_COPY.items()
            ],
        )
    return len(HEXAGRAM_PROFILE_COPY)


def seed_demo_evaluation(path: Path | None = None, cases_path: Path = DEMO_CASES_PATH) -> int:
    target_path = initialize_database(path)
    cases = load_retrieval_cases(cases_path)
    with _connect(target_path) as connection:
        connection.executemany(
            """
            INSERT INTO semantic_codes (code, dimension, label, definition)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (code) DO UPDATE SET
                dimension = excluded.dimension,
                label = excluded.label,
                definition = excluded.definition
            """,
            SEMANTIC_CODES,
        )
        connection.executemany(
            """
            INSERT INTO retrieval_cases (
                case_key, query, expected_codes, expected_hexagram_keys,
                must_not_return_hexagram_keys, rationale
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (case_key) DO UPDATE SET
                query = excluded.query,
                expected_codes = excluded.expected_codes,
                expected_hexagram_keys = excluded.expected_hexagram_keys,
                must_not_return_hexagram_keys = excluded.must_not_return_hexagram_keys,
                rationale = excluded.rationale
            """,
            [
                (
                    case.case_key,
                    case.query,
                    json.dumps(case.expected_codes, ensure_ascii=False),
                    json.dumps(case.expected_hexagram_keys, ensure_ascii=False),
                    json.dumps(case.must_not_return_hexagram_keys, ensure_ascii=False),
                    case.rationale,
                )
                for case in cases
            ],
        )
    return len(cases)


def download_freizl_yijing(destination: Path = FREIZL_YIJING_ARCHIVE_PATH) -> Path:
    """Download the corpus from an immutable Git revision for local review and import."""
    with urlopen(FREIZL_YIJING_SOURCE_URL, timeout=30) as response:
        payload = response.read()
    if not payload:
        raise ValueError("The downloaded Yijing corpus is empty.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return destination


def import_freizl_yijing(
    source_path: Path = FREIZL_YIJING_ARCHIVE_PATH,
    path: Path | None = None,
) -> ClassicalTextImport:
    """Import the pinned 64-gua corpus after verifying its complete canonical coverage."""
    source_bytes = source_path.read_bytes()
    source_sha256 = sha256(source_bytes).hexdigest()
    try:
        payload = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("The Yijing corpus must be UTF-8 JSON.") from error
    if not isinstance(payload, list):
        raise ValueError("The Yijing corpus must contain a list of hexagrams.")

    expected_keys = {entry.binary_key for entry in hexagram_catalog()}
    entries_by_key: dict[str, dict[str, object]] = {}
    for entry in payload:
        if not isinstance(entry, dict):
            raise ValueError("Each Yijing corpus entry must be an object.")
        source_key = entry.get("id")
        gua_ci = entry.get("gua_ci")
        yao_ci = entry.get("yao_ci")
        if not isinstance(source_key, str) or len(source_key) != 6 or set(source_key) - {"0", "1"}:
            raise ValueError("The Yijing corpus has a missing or duplicate hexagram id.")
        # The corpus encodes lower trigram before upper trigram; the engine uses the opposite order.
        key = source_key[3:] + source_key[:3]
        if key in entries_by_key:
            raise ValueError("The Yijing corpus has a missing or duplicate hexagram id.")
        if not isinstance(gua_ci, str) or not gua_ci.strip():
            raise ValueError(f"Hexagram {key} is missing gua_ci.")
        if not isinstance(yao_ci, list) or len(yao_ci) < 6 or any(
            not isinstance(item, str) or not item.strip() for item in yao_ci[:6]
        ):
            raise ValueError(f"Hexagram {key} must contain at least six non-empty yao_ci entries.")
        entries_by_key[key] = entry
    if set(entries_by_key) != expected_keys:
        raise ValueError("The Yijing corpus does not cover the canonical 64 hexagrams exactly.")

    target_path = path or database_path()
    seed_hexagrams(target_path)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    edition = (
        FREIZL_YIJING_EDITION_ID,
        "《易经》六十四卦卦辞、爻辞（freizl/yijing zh-CN）",
        f"Git revision {FREIZL_YIJING_REVISION}; file zh-CN/64gua.json.",
        "MIT License declared by freizl/yijing; the imported corpus is retained with its immutable source URL and hash.",
        FREIZL_YIJING_SOURCE_URL,
        retrieved_at,
        source_sha256,
    )
    source_rows: list[tuple[str, str, str, int | None, str, str, str]] = []
    for key in sorted(entries_by_key):
        entry = entries_by_key[key]
        locator = f"zh-CN/64gua.json#id={entry['id']}"
        gua_ci = str(entry["gua_ci"]).strip()
        source_rows.append(
            (
                f"{FREIZL_YIJING_EDITION_ID}:{key}:gua_ci",
                FREIZL_YIJING_EDITION_ID,
                key,
                None,
                "gua_ci",
                gua_ci,
                locator,
            )
        )
        for position, yao_ci in enumerate(entry["yao_ci"][:6], start=1):
            body = str(yao_ci).strip()
            source_rows.append(
                (
                    f"{FREIZL_YIJING_EDITION_ID}:{key}:yao_ci:{position}",
                    FREIZL_YIJING_EDITION_ID,
                    key,
                    position,
                    "yao_ci",
                    body,
                    f"{locator}:yao_ci[{position}]",
                )
            )

    with _connect(target_path) as connection:
        existing = connection.execute(
            "SELECT content_sha256 FROM editions WHERE id = ?", (FREIZL_YIJING_EDITION_ID,)
        ).fetchone()
        if existing is not None and existing["content_sha256"] != source_sha256:
            raise ValueError("The archived corpus differs from the source already recorded for this revision.")
        connection.execute(
            """
            INSERT INTO editions (id, title, edition_note, license_basis, source_url, retrieved_at, content_sha256)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET retrieved_at = excluded.retrieved_at
            """,
            edition,
        )
        connection.executemany(
            """
            INSERT INTO source_texts (
                id, edition_id, hexagram_key, line_position, text_kind, body, locator, content_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                body = excluded.body,
                locator = excluded.locator,
                content_sha256 = excluded.content_sha256
            """,
            [
                (*row, sha256(row[5].encode("utf-8")).hexdigest())
                for row in source_rows
            ],
        )
    return ClassicalTextImport(source_path, source_sha256, len(entries_by_key), len(source_rows))


def get_hexagram(binary_key: str, path: Path | None = None) -> dict[str, object] | None:
    target_path = path or database_path()
    seed_hexagram_profiles(target_path)
    with _connect(target_path) as connection:
        row = connection.execute(
            """
            SELECT hexagram.binary_key, hexagram.king_wen_no, hexagram.name,
                   hexagram.upper_trigram, hexagram.lower_trigram,
                   COUNT(source_text.id) AS source_text_count
            FROM hexagrams AS hexagram
            LEFT JOIN source_texts AS source_text ON source_text.hexagram_key = hexagram.binary_key
            WHERE hexagram.binary_key = ?
            GROUP BY hexagram.binary_key
            """,
            (binary_key,),
        ).fetchone()
    return dict(row) if row else None


def get_hexagram_profile(binary_key: str, path: Path | None = None) -> dict[str, str] | None:
    target_path = path or database_path()
    seed_hexagram_profiles(target_path)
    with _connect(target_path) as connection:
        row = connection.execute(
            """
            SELECT hexagram.binary_key, hexagram.name, profile.overview,
                   profile.change_focus, profile.provenance
            FROM hexagram_profiles AS profile
            JOIN hexagrams AS hexagram ON hexagram.binary_key = profile.hexagram_key
            WHERE profile.hexagram_key = ?
            """,
            (binary_key,),
        ).fetchone()
    return dict(row) if row else None


def get_classical_hexagram_texts(binary_key: str, path: Path | None = None) -> dict[str, object]:
    target_path = path or database_path()
    seed_hexagrams(target_path)
    with _connect(target_path) as connection:
        rows = connection.execute(
            """
            SELECT text.text_kind, text.line_position, text.body, text.locator,
                   edition.id AS edition_id, edition.title AS edition_title,
                   edition.source_url, edition.license_basis
            FROM source_texts AS text
            JOIN editions AS edition ON edition.id = text.edition_id
            WHERE text.hexagram_key = ?
            ORDER BY edition.retrieved_at DESC, text.text_kind, text.line_position
            """,
            (binary_key,),
        ).fetchall()
    gua_ci: dict[str, object] | None = None
    yao_ci: dict[int, dict[str, object]] = {}
    for row in rows:
        item = dict(row)
        if item["text_kind"] == "gua_ci" and gua_ci is None:
            gua_ci = item
        elif item["text_kind"] == "yao_ci" and item["line_position"] not in yao_ci:
            yao_ci[item["line_position"]] = item
    return {"gua_ci": gua_ci, "yao_ci": yao_ci}


def build_transition_reading(casting: Casting, path: Path | None = None) -> dict[str, object]:
    original = get_hexagram_profile(casting.original.binary_key, path)
    changed = get_hexagram_profile(casting.changed.binary_key, path)
    if original is None or changed is None:
        raise RuntimeError("The direct profile catalog is incomplete.")
    moving_lines = list(casting.moving_line_positions)
    if not moving_lines:
        display = f"本次无动爻，维持“{original['name']}”的主题：{original['overview']}"
    else:
        positions = "、".join(f"第{position}爻" for position in moving_lines)
        display = (
            f"{positions}发动。可从“{original['name']}”的{original['overview']}"
            f"转向“{changed['name']}”的{changed['change_focus']}"
        )
    original_texts = get_classical_hexagram_texts(casting.original.binary_key, path)
    changed_texts = get_classical_hexagram_texts(casting.changed.binary_key, path)
    return {
        "original": original,
        "changed": changed,
        "moving_line_positions": moving_lines,
        "display": display,
        "provenance": "editorial_demo",
        "disclaimer": "这是基于卦象结构的编辑性展示，不是经典原文引文或确定性预测。",
        "classical_texts": {
            "original_gua_ci": original_texts["gua_ci"],
            "changed_gua_ci": changed_texts["gua_ci"],
            "moving_lines": [
                original_texts["yao_ci"].get(position)
                for position in moving_lines
            ],
        },
    }


def main() -> None:
    hexagram_count = seed_hexagrams()
    profile_count = seed_hexagram_profiles()
    print(f"Seeded {hexagram_count} hexagrams and {profile_count} direct profiles into {database_path()}.")


def seed_demo_evaluation_main() -> None:
    count = seed_demo_evaluation()
    print(f"Seeded {count} retrieval cases into {database_path()}.")


def import_freizl_yijing_main() -> None:
    source_path = download_freizl_yijing()
    imported = import_freizl_yijing(source_path)
    print(
        f"Imported {imported.source_text_count} classical texts for {imported.hexagram_count} hexagrams "
        f"from {imported.source_path} into {database_path()}."
    )