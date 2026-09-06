"""Riding-name normalisation.

`name_key` is the single definition of how a riding name is matched across the
repo: the seed CSVs, the reference build scripts, the loader and the tests all
use this function, so the matching rule can only ever change in one place.

Folded, in order: em/en dashes to hyphen, apostrophe variants to the straight
apostrophe, the oe/OE ligatures to two letters (the 2023 Representation Order
spells Île-des-Soeurs with two letters; recovered seed text used the ligature),
whitespace collapsed, then case-folded.
"""

import re

__all__ = ["name_key"]


def name_key(name):
    key = name.replace("—", "-").replace("–", "-")
    key = key.replace("’", "'").replace("‘", "'")
    key = key.replace("œ", "oe").replace("Œ", "OE")
    key = re.sub(r"\s+", " ", key).strip()
    return key.casefold()
