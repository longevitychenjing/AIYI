from dataclasses import dataclass
from enum import Enum
from typing import Sequence


class LineValue(int, Enum):
    OLD_YIN = 6
    YOUNG_YANG = 7
    YOUNG_YIN = 8
    OLD_YANG = 9


class CoinSide(str, Enum):
    HEADS = "heads"
    TAILS = "tails"


@dataclass(frozen=True)
class Hexagram:
    name: str
    binary_key: str


@dataclass(frozen=True)
class Casting:
    lines: tuple[LineValue, ...]
    original: Hexagram
    changed: Hexagram
    moving_line_positions: tuple[int, ...]


TRIGRAMS = {
    "111": "乾",
    "110": "兑",
    "101": "离",
    "100": "震",
    "011": "巽",
    "010": "坎",
    "001": "艮",
    "000": "坤",
}


HEXAGRAM_NAMES = {
    "111111": "乾为天", "110111": "泽天夬", "101111": "火天大有", "100111": "雷天大壮",
    "011111": "风天小畜", "010111": "水天需", "001111": "山天大畜", "000111": "地天泰",
    "111110": "天泽履", "110110": "兑为泽", "101110": "火泽睽", "100110": "雷泽归妹",
    "011110": "风泽中孚", "010110": "水泽节", "001110": "山泽损", "000110": "地泽临",
    "111101": "天火同人", "110101": "泽火革", "101101": "离为火", "100101": "雷火丰",
    "011101": "风火家人", "010101": "水火既济", "001101": "山火贲", "000101": "地火明夷",
    "111100": "天雷无妄", "110100": "泽雷随", "101100": "火雷噬嗑", "100100": "震为雷",
    "011100": "风雷益", "010100": "水雷屯", "001100": "山雷颐", "000100": "地雷复",
    "111011": "天风姤", "110011": "泽风大过", "101011": "火风鼎", "100011": "雷风恒",
    "011011": "巽为风", "010011": "水风井", "001011": "山风蛊", "000011": "地风升",
    "111010": "天水讼", "110010": "泽水困", "101010": "火水未济", "100010": "雷水解",
    "011010": "风水涣", "010010": "坎为水", "001010": "山水蒙", "000010": "地水师",
    "111001": "天山遁", "110001": "泽山咸", "101001": "火山旅", "100001": "雷山小过",
    "011001": "风山渐", "010001": "水山蹇", "001001": "艮为山", "000001": "地山谦",
    "111000": "天地否", "110000": "泽地萃", "101000": "火地晋", "100000": "雷地豫",
    "011000": "风地观", "010000": "水地比", "001000": "山地剥", "000000": "坤为地",
}


def cast(line_values: Sequence[int | LineValue]) -> Casting:
    if len(line_values) != 6:
        raise ValueError("A casting must contain exactly six lines, from bottom to top.")

    lines = tuple(LineValue(value) for value in line_values)
    bottom_to_top = "".join("0" if line in (LineValue.OLD_YIN, LineValue.YOUNG_YIN) else "1" for line in lines)
    changed_bottom_to_top = "".join(
        "1" if line is LineValue.OLD_YIN else "0" if line is LineValue.OLD_YANG else bit
        for line, bit in zip(lines, bottom_to_top, strict=True)
    )
    # The table is keyed by upper trigram then lower trigram, while callers enter initial to upper line.
    original_key = bottom_to_top[3:] + bottom_to_top[:3]
    changed_key = changed_bottom_to_top[3:] + changed_bottom_to_top[:3]
    moving_positions = tuple(index + 1 for index, line in enumerate(lines) if line in (LineValue.OLD_YIN, LineValue.OLD_YANG))
    return Casting(
        lines=lines,
        original=Hexagram(name=HEXAGRAM_NAMES[original_key], binary_key=original_key),
        changed=Hexagram(name=HEXAGRAM_NAMES[changed_key], binary_key=changed_key),
        moving_line_positions=moving_positions,
    )


def cast_from_coins(tosses: Sequence[Sequence[CoinSide | str]]) -> LineValue:
    if len(tosses) != 3:
        raise ValueError("Each line must be cast with exactly three coins.")
    sides = tuple(CoinSide(side) for side in tosses)
    return LineValue(sum(3 if side is CoinSide.HEADS else 2 for side in sides))