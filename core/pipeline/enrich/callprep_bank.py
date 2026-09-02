"""Practical, deterministic prompts for a call and apartment viewing."""

from core.domain.costs import is_missing_info
from core.domain.money_field import is_missing as money_is_missing


_ALWAYS_ON = [
    "Na jak długo właściciel chce wynająć mieszkanie i czy przewiduje przedłużenie umowy?",
    "Co dokładnie zostaje w mieszkaniu, a co właściciel planuje zabrać?",
]

VIEWING_CHECKLIST = [
    "Czy mieszkanie jest tak jasne, jak wyglądało na zdjęciach?",
    "Czy nie widać zacieków, pleśni ani śladów wilgoci?",
    "Czy okna, drzwi, krany i odpływy działają bez problemu?",
    "Czy sprzęty i meble, które zostają, są w dobrym stanie?",
    "Jak wygląda klatka, wejście do budynku i okolica po zmroku?",
    "Czy miejsce parkingowe, komórka i inne dodatki odpowiadają opisowi?",
]


def build_callprep(listing) -> dict:
    """Return questions based only on information missing from ``listing``."""
    missing: list[str] = []

    if is_missing_info(listing.heating):
        missing.append("Jakie jest rodzaj ogrzewania i czy jego koszt jest już w czynszu, czy rozliczany osobno?")
    if money_is_missing(listing.parking):
        missing.append("Czy miejsce parkingowe jest przypisane do mieszkania? Gdzie jest i ile kosztuje?")
    if money_is_missing(listing.piwnica):
        missing.append("Czy do mieszkania należy piwnica lub komórka lokatorska? Jeśli tak, czy jest w cenie?")
    if money_is_missing(listing.deposit):
        missing.append("Ile dokładnie wynosi kwota kaucji i w jakich sytuacjach może zostać potrącona?")
    if money_is_missing(listing.notariusz):
        missing.append("Czy obowiązuje najem okazjonalny? Kto organizuje oświadczenie notarialne i kto za nie płaci?")
    if money_is_missing(listing.prowizja):
        missing.append("Czy jest prowizja? Jeśli tak, jaka jest kwota prowizji i kiedy trzeba ją zapłacić?")
    if money_is_missing(listing.oc):
        missing.append("Czy wymagane jest OC najemcy?")
    if listing.pets_allowed is None:
        missing.append("Czy właściciel akceptuje zwierzęta? Czy są dodatkowe warunki albo opłaty?")
    if listing.posrednik is None:
        missing.append("Czy rozmawiam z właścicielem, czy z pośrednikiem?")

    breakdown = getattr(listing, "cost_breakdown", None)
    if breakdown:
        unclear = [
            key for key in ("prad", "gaz", "internet", "woda", "ogrzewanie", "smieci")
            if breakdown.get("utilities", {}).get(key, {}).get("status")
            in ("osobno_bez_kwoty", "brak_informacji")
        ]
        if unclear:
            from core.domain.breakdown import LABELS_PL_NOM
            names = ", ".join(LABELS_PL_NOM[key] for key in unclear)
            missing.append(f"Jak rozliczane są {names}: ryczałt, zaliczka czy liczniki? Ile średnio wychodziło w ostatnich miesiącach?")

    if listing.available_from is None:
        missing.append("Od kiedy można się wprowadzać")

    return {"missing": missing[:8], "always": list(_ALWAYS_ON), "viewing": list(VIEWING_CHECKLIST)}
