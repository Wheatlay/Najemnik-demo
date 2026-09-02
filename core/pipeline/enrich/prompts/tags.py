"""Amenity-tagging prompt (SPEC §9.2). v4 - one strict yes/no question per
tag instead of one call asking the model to pick a subset from the whole
vocabulary. v3 already restricted the model to a fixed vocabulary, but a
single "pick which of these apply" call still let it hallucinate a pick
against its own instructions (e.g. tagging "nie umeblowane" onto a listing
whose text clearly lists furniture). Splitting into one yes/no question per
tag mirrors the pattern already used for parking/piwnica/etc in
field_specs.py, and each answer is validated independently."""
VERSION = 4

TEMPLATE = """Analizujesz ogłoszenie wynajmu mieszkania.

Treść ogłoszenia:
{raw_text}

Pytanie: czy treść ogłoszenia WPROST potwierdza cechę "{tag}"?
Odpowiedz "tak" TYLKO jeśli ta cecha (lub jej oczywisty synonim) faktycznie jest potwierdzona w treści ogłoszenia. Jeśli tekst nic o tym nie mówi, albo mówi coś przeciwnego, odpowiedz "nie". Nie zgaduj.

Zwróć WYŁĄCZNIE obiekt JSON: {{"answer": "tak"/"nie"}}"""


def build_prompt(listing, tag: str) -> str:
    return TEMPLATE.format(raw_text=(listing.raw_text or "")[:4000], tag=tag)
