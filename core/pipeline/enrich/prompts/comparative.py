"""Comparative analysis prompt (SPEC §9.5), run over the current filtered
set. v3 - v2 still let the model recompute/reformat numbers itself (giving
inconsistent "40880 zł" instead of "40 880 zł") and infer distance-to-center
from the title/description rather than the actual commute-time fields.
Now every number is pre-formatted in Python and the model is told to copy
it verbatim, in a fixed order (wejście -> miesięcznie -> rok), and location
comparisons are restricted to the explicit commute_time_car/public fields -
omitted entirely when neither is filled in, rather than guessed."""
VERSION = 3

TEMPLATE = """Porównaj poniższe mieszkania do wynajęcia (ta sama grupa, którą użytkownik aktualnie przegląda) i dla KAŻDEGO z nich podaj konkretną, użyteczną ocenę na tle pozostałych z tej listy.

ZASADY:
- Kwoty (koszt wejścia, koszt miesięczny, koszt roku) są już policzone i sformatowane poniżej - PRZEPISZ je dokładnie tak jak podane (z spacją co trzy cyfry, np. "40 880 zł"). NIE licz ich samodzielnie od nowa i nie zmieniaj formatu zapisu.
- W ocenie ZAWSZE odnieś się do kosztów w tej kolejności: koszt wejścia (jednorazowy), koszt miesięczny, całkowity koszt pierwszego roku (to najważniejsza liczba - suma, którą realnie użytkownik wyda w ciągu roku, więc kontekst "rocznie" musi być jawnie napisany, nie samo "droższe").
- NIE porównuj mieszkań po cenie za m2 ani po drobnych różnicach powierzchni (kilka m2 różnicy nie ma praktycznego znaczenia dla komfortu życia).
- Odległość/dojazd komentuj WYŁĄCZNIE na podstawie podanych niżej pól "czas dojazdu (auto)"/"czas dojazdu (komunikacja)" - jeśli oba są puste, w ogóle nie wspominaj o lokalizacji/odległości od centrum, nawet jeśli nazwa dzielnicy czy opis coś sugerują.
- Traktuj konkretne udogodnienia/ich brak jako istotne kryteria jakości życia: piwnica, miejsce parkingowe/garaż, winda, zmywarka, klimatyzacja, balkon, meble, zgoda na zwierzęta. Wskaż różnice w tym zakresie między porównywanymi ofertami.

Mieszkania:
{items}

Zwróć WYŁĄCZNIE obiekt JSON w postaci: {{"<id>": {{"porownanie": "1-2 zdania - koszt wejścia, koszt miesięczny, koszt roku (skopiowane dokładnie jak podano), plus realna ocena na tle reszty", "plusy": ["+ konkret, np. kwota lub udogodnienie"], "minusy": ["- konkret"]}}, ...}} dla każdego id z listy powyżej."""


def build_prompt(listings) -> str:
    from core.domain.costs import suma_miesieczna, suma_wejscia
    from core.domain.normalize import format_money

    lines = []
    for l in listings:
        monthly = suma_miesieczna(l)
        entry = suma_wejscia(l)
        first_year = (monthly or 0) * 12 + (entry or 0) if (monthly or entry) else None
        pets = "brak informacji" if l.pets_allowed is None else ("tak" if l.pets_allowed else "nie")
        commute = "; ".join(
            c for c in (
                f"auto: {l.commute_time_car}" if l.commute_time_car else "",
                f"komunikacja: {l.commute_time_public}" if l.commute_time_public else "",
            ) if c
        ) or "brak danych o czasie dojazdu"
        lines.append(
            f"- id={l.id}: {l.title}, {l.area_m2} m2, {l.rooms} pok., dzielnica={l.district}\n"
            f"  Koszt wejścia (kaucja+notariusz+prowizja): {format_money(entry)}\n"
            f"  Koszt miesięczny (czynsz+admin+opłaty+ogrzewanie+parking): {format_money(monthly)}\n"
            f"  Koszt 1. roku najmu (koszt miesięczny x12 + koszt wejścia): {format_money(first_year)}\n"
            f"  Czas dojazdu: {commute}\n"
            f"  Zwierzęta dozwolone: {pets}\n"
            f"  Udogodnienia (tagi): {', '.join(l.tags) if l.tags else 'brak podanych tagów'}"
        )
    return TEMPLATE.format(items="\n".join(lines))
