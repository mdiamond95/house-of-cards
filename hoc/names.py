"""Names: riding-name normalisation, and the engine's name generator.

`name_key` is the single definition of how a riding name is matched across the
repo: the seed CSVs, the reference build scripts, the loader and the tests all
use this function, so the matching rule can only ever change in one place.

Folded, in order: em/en dashes to hyphen, apostrophe variants to the straight
apostrophe, the oe/OE ligatures to two letters (the 2023 Representation Order
spells Île-des-Soeurs with two letters; recovered seed text used the ligature),
whitespace collapsed, then case-folded.
"""

import csv
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

__all__ = [
    "name_key",
    "NameError_",
    "NameGenerator",
    "load_denylist",
    "peerage_title",
    "french_particle",
]


def name_key(name):
    key = name.replace("—", "-").replace("–", "-")
    key = key.replace("’", "'").replace("‘", "'")
    key = key.replace("œ", "oe").replace("Œ", "OE")
    key = re.sub(r"\s+", " ", key).strip()
    return key.casefold()


# ------------------------------------------------------- the name generator --
#
# A house is named by pairing a surname from its cultural community's bank with
# a given name from that community's naming tradition (rules/README.md, Naming
# policy). The banks describe real communities, so two rules bind the generator:
# it never produces the full name of a well-known real person (rules/denylist.csv),
# and it never reuses a territorial designation that a living house still holds.


class NameError_(Exception):
    """The banks cannot satisfy a name request."""


DENYLIST_PATH = Path(__file__).resolve().parent.parent / "rules" / "denylist.csv"

# How many redraws before we conclude the bank is too small to avoid a collision.
# Well above the worst case: the smallest community bank holds 15 surnames and
# the denylist blocks at most a handful of pairs in any one of them.
MAX_REDRAWS = 50


def _fold(name):
    """Compare names case- and accent-insensitively, so 'Thérèse Casgrain' on the
    denylist also blocks 'Therese Casgrain'. Punctuation and spacing are
    normalised too: a denylist is worth little if a hyphen defeats it."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("'", "'").replace("-", " ").replace("-", " ")
    return re.sub(r"\s+", " ", text).strip().casefold()


def load_denylist(path=DENYLIST_PATH):
    """The set of folded full names the generator must never produce."""
    with open(path, newline="", encoding="utf-8") as f:
        return {_fold(row["full_name"]) for row in csv.DictReader(f)}


VOWELS = "aeiouyàâäéèêëîïôöùûü"


def french_particle(place):
    """The particle joining a French-tradition peerage to its territory.

    French usage, not a translation rule: `de` before a consonant, elided to `d'`
    before a vowel, contracted to `du` / `de la` / `des` when the place name
    carries its own article. An English article on a place name ('the Red River')
    is dropped rather than translated — the engine does not invent a French form
    of a place that has none.
    """
    place = place.strip()
    lowered = place.lower()

    if lowered.startswith("the "):
        place = place[4:].strip()
        lowered = place.lower()

    if lowered.startswith("le "):
        return "du", place[3:].strip()
    if lowered.startswith("la "):
        return "de la", place[3:].strip()
    if lowered.startswith("les "):
        return "des", place[4:].strip()
    if lowered.startswith("l'"):
        return "de l'", place[2:].strip()

    if lowered[:1] in VOWELS:
        return "d'", place
    return "de", place


def peerage_title(rank, surname, place, tradition):
    """'<Rank> <Surname> of <place>', with French tradition taking the particle.

    Every tradition other than french uses 'of': an Anishinaabe or Icelandic
    house in this Canada holds a Crown peerage in English, and inventing a
    particle for a tradition that has none would be fabrication, not flavour.
    """
    if tradition == "french":
        particle, tail = french_particle(place)
        if particle.endswith("'"):
            return f"{rank} {surname} {particle}{tail}"
        return f"{rank} {surname} {particle} {tail}"
    return f"{rank} {surname} of {place}"


class NameGenerator:
    """Draws people, places and peerage titles from the rules banks.

    `rng` need only provide `choice(sequence)`; the engine passes a wrapper that
    logs every draw to the season record, so a generated name is reproducible
    from the seed and auditable from the log.
    """

    def __init__(self, rules, rng, denylist=None):
        self.rng = rng
        self.denylist = load_denylist() if denylist is None else set(denylist)

        self.surnames_by_community = defaultdict(list)
        for row in rules.surnames:
            self.surnames_by_community[row.community].append(row.surname)

        self.given_by_tradition = defaultdict(list)
        for row in rules.given_names:
            self.given_by_tradition[(row.tradition, row.gender)].append(row.name)

        self.places_by_province = defaultdict(list)
        for row in rules.places:
            self.places_by_province[row.province].append(row.place)

        self.tradition_by_community = {c.community: c.naming_tradition for c in rules.communities}

    # -- people --

    def tradition_for(self, community):
        tradition = self.tradition_by_community.get(community)
        if tradition is None:
            raise NameError_(f"no naming tradition recorded for community {community!r}")
        return tradition

    def draw_gender(self):
        return self.rng.choice(["m", "f"])

    def draw_person(self, community, gender=None, surname=None):
        """(given_name, surname, gender) for a member of a community.

        A surname may be fixed — an heir carries the house's name — in which case
        only the given name is drawn. Redraws on any denylist collision.
        """
        tradition = self.tradition_for(community)
        gender = gender or self.draw_gender()

        surnames = self.surnames_by_community.get(community)
        if not surnames:
            raise NameError_(f"no surnames in the bank for community {community!r}")
        givens = self.given_by_tradition.get((tradition, gender))
        if not givens:
            raise NameError_(f"no {gender!r} given names in the bank for tradition {tradition!r}")

        for _ in range(MAX_REDRAWS):
            drawn_surname = surname if surname is not None else self.rng.choice(surnames)
            given = self.rng.choice(givens)
            if _fold(f"{given} {drawn_surname}") not in self.denylist:
                return given, drawn_surname, gender

        raise NameError_(
            f"could not draw a name for community {community!r} in {MAX_REDRAWS} attempts"
            " without reproducing a name on rules/denylist.csv"
        )

    # -- places --

    def draw_place(self, province, taken=()):
        """A territorial designation from the seat's province, not already in use.

        Raises when the province's bank is exhausted: the engine must decide what
        to do about a province with more houses than place names, and silently
        reusing a designation would make two houses indistinguishable.
        """
        places = self.places_by_province.get(province)
        if not places:
            raise NameError_(f"no places in the bank for province {province!r}")
        taken = {p for p in taken}
        available = [p for p in places if p not in taken]
        if not available:
            raise NameError_(
                f"every place in the {province} bank is already held"
                f" ({len(places)} names, {len(taken)} in use)"
            )
        return self.rng.choice(available)

    def draw_house(self, community, province, rank, taken_places=(), gender=None):
        """Everything a founding needs: (surname, given, gender, place, peerage)."""
        given, surname, gender = self.draw_person(community, gender=gender)
        place = self.draw_place(province, taken_places)
        tradition = self.tradition_for(community)
        return {
            "surname": surname,
            "given": given,
            "gender": gender,
            "place": place,
            "tradition": tradition,
            "peerage": peerage_title(rank, surname, place, tradition),
        }
