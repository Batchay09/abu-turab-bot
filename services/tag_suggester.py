"""
Smart tag suggestion based on question content.
Uses keyword matching to suggest relevant tags.
"""

import re
from typing import List

# Keywords for each tag
TAG_KEYWORDS = {
    "намаз": ["намаз", "молитв", "салят", "салат", "ракаат", "суджуд", "руку", "кыям", "ташаххуд", "фаджр", "зухр", "аср", "магриб", "иша", "джума", "витр", "тахаджуд"],
    "закят": ["закят", "закат", "садак", "милостын", "нисаб", "2.5%"],
    "пост": ["пост", "саум", "ураз", "ифтар", "сухур", "рамадан", "рамазан", "говен", "разговен"],
    "хадж": ["хадж", "паломничеств", "кааб", "мекк", "мина", "арафа", "муздалиф", "тальбия"],
    "умра": ["умра", "малое паломничество"],
    "тахарат": ["омовен", "тахар", "вуду", "гусль", "таяммум", "наджас", "нечистот", "истинджа", "мытьё", "купан"],
    "никах": ["никах", "никях", "брак", "женитьб", "свадьб", "замуж", "жена", "муж", "супруг", "махр", "валима", "сватов"],
    "талак": ["талак", "талякъ", "развод", "идда", "хула"],
    "торговля": ["торговл", "купл", "продаж", "бизнес", "риба", "процент", "кредит", "ипотек", "банк", "долг", "займ", "харам деньг"],
    "наследство": ["наследств", "наслед", "завещан", "васият"],
    "еда": ["еда", "пища", "халяль", "харам", "мясо", "забой", "забиха", "алкогол", "желатин", "есть", "кушать", "продукт"],
    "одежда": ["одежд", "аурат", "хиджаб", "никаб", "платок", "покрыт", "носить", "золот", "шёлк", "серебр"],
    "акыда": ["акыда", "акида", "вероубежден", "вера", "иман"],
    "таухид": ["таухид", "единобожи"],
    "ширк": ["ширк", "многобожи", "идол", "могил", "мазар", "тавассуль"],
    "семья": ["семь", "родител", "мать", "отец", "дети", "ребён", "сын", "дочь", "брат", "сестр", "родств"],
    "воспитание": ["воспитан", "дети", "ребён", "обуч"],
    "женщинам": ["женщин", "хайд", "месячн", "нифас", "менструац", "беремен", "кормлен"],
    "похороны": ["похорон", "джаназ", "смерт", "умер", "кладбищ", "могил", "кафан", "погреб", "дафн"],
    "дуа": ["дуа", "ду'а", "мольб", "зикр", "поминан", "азкар", "просьб"],
    "Коран": ["коран", "аят", "сур", "чтен", "тиляв", "таджвид", "хафиз"],
    "хадисы": ["хадис", "сунн", "пророк", "посланник", "сахих", "иснад"],
    "общее": [],  # fallback
}


def suggest_tags(question_text: str, top_n: int = 3) -> List[str]:
    """
    Suggest relevant tags based on question content.

    Args:
        question_text: The question text
        top_n: Number of tags to suggest

    Returns:
        List of suggested tag names
    """
    question_lower = question_text.lower()

    # Score each tag based on keyword matches
    scores = {}

    for tag_name, keywords in TAG_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            # Count occurrences of keyword in question
            matches = len(re.findall(keyword, question_lower))
            score += matches

        if score > 0:
            scores[tag_name] = score

    # Sort by score descending
    sorted_tags = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    # Return top N tags
    suggested = [tag for tag, score in sorted_tags[:top_n]]

    # If no matches found, suggest "общее"
    if not suggested:
        suggested = ["общее"]

    return suggested


def get_all_tag_names() -> List[str]:
    """Get list of all available tag names."""
    return list(TAG_KEYWORDS.keys())
