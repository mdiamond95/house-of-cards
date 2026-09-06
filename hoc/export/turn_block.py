"""The Code block the console hands the director for narration.

Claude is not part of any workflow in this repo — no API key, no Action, no
call. What the console produces is a block of text for the director to paste
into a Claude Code session, and everything Claude is asked to do there it does
under the same rules as any other session in this repo: from the record, in
Canadian English, committed on a branch and merged by a pull request.

The template lives here rather than in the console's JavaScript so that the
instructions Claude receives are versioned with the code that generates them,
and so the same block can be produced from a Code session with
`python -m hoc narrate 40 60`.
"""

__all__ = ["TONES", "narrate_block", "TEMPLATE"]

# What kind of prose the director wants. The tone is a real instruction, not a
# label: each names a voice the record can actually support.
TONES = {
    "chronicle": (
        "the measured voice of a house chronicle — third person, past tense,"
        " a paragraph to a season, more interested in consequence than incident"
    ),
    "intimate": (
        "close on the people — what a holder or an heir made of the season,"
        " in their own house's idiom, without inventing anything the record"
        " does not hold"
    ),
    "official gazette": (
        "the flat institutional register of a Dominion gazette — notices,"
        " appointments, grants and deaths, dated by each house's personal year"
    ),
}

TEMPLATE = """Follow CLAUDE.md. Narrate seasons {season_from}–{season_to} of the live \
(new) scenario.{focus}

Tone: {tone_description}.

Sources, and nothing else:
- `scenarios/new/seasons/{season_from:04d}.json` through `{season_to:04d}.json` — every roll, \
draw and outcome, with the purpose each was drawn for.
- The chronicle lines already in `hoc.db` for those seasons (`events.narrative` \
where the event's `mechanical_delta` names one of them).
- House detail from `hoc.db` only — house_stats, persons, objectives, holdings, \
relations, house_blocks. CLAUDE.md hard rule 9 applies: if a detail is not in the \
database, it does not go in the prose.

Do not invent settlers, dates, relations, colours or events. Do not give a house \
a personal year it did not reach. There is no universal calendar: each house's \
dates are its own clock's, and two houses share a year only where the record says \
they met.

Write it to `narratives/{season_from:04d}-{season_to:04d}.md` with this front matter:

    ---
    seasons: {season_from}-{season_to}
    tone: {tone}
    ---

Then run `python -m hoc export` so the chronicle picks it up, commit the \
narrative and `outputs/` together, push, open a PR and merge it.

Length: about {words} words. Canadian spelling throughout."""


def narrate_block(season_from, season_to, houses=(), tone="chronicle"):
    """The block, ready to paste into a Claude Code session."""
    if tone not in TONES:
        raise ValueError(f"unknown tone {tone!r}; choose one of {', '.join(sorted(TONES))}")
    if season_to < season_from:
        season_from, season_to = season_to, season_from

    names = [name for name in houses if name]
    focus = ""
    if names:
        focus = (
            " Focus on "
            + (", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0])
            + ", and mention other houses only where they touch these."
        )

    # Roughly 120 words a season, floored so a one-season range still gets prose
    # and capped so a long range does not ask for an essay.
    span = season_to - season_from + 1
    words = max(300, min(1200, span * 120))

    return TEMPLATE.format(
        season_from=season_from,
        season_to=season_to,
        focus=focus,
        tone=tone,
        tone_description=TONES[tone],
        words=words,
    )
