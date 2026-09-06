"""The autoplay engine: houses that play themselves, season by season.

One **season** is a tick. Every house's personal clock advances a year, every
living named person ages a year, the holder rolls against mortality, any era
event standing at the house's personal year fires, the house draws and resolves
one action, its objectives are checked, and — at the end of the season — the
founding roll may add a house somewhere on the map.

Three things are load-bearing:

* **Determinism.** Everything random comes from `season_rng(season_no)`, seeded
  from the world seed and the season number alone, and every draw is written to
  the season log with the purpose it was drawn for. Two worlds with the same
  seed play the same game; a season log is enough to audit any outcome.
* **No world clock.** Each house keeps a personal year in `clocks`; foundings and
  successions reset it to 1867 (hard rule 5). The season counter is bookkeeping,
  not a date, so two houses in the same season are usually in different eras and
  read the event deck at different points.
* **The rules live in `rules/`, not here.** Weights, targets, probabilities and
  banks are loaded through `hoc.rules_data`. Tuning the game means editing a
  table and recording it in `rules/CHANGELOG.md`; it never means editing this
  file (docs/ENGINE_DESIGN.md §11).

Phase 9c PART A implements the expansion-era actions — Expand, Invest, Cultivate
influence, Name heir, Endow, Petition elevation, Consolidate (rest) — with the
§7c riding losses (contraction sale, debt). The relational and late-game actions
are recognised and weighted zero until PART B.
"""

import hashlib
import json
import math
import random
from collections import defaultdict
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path

from hoc import palette, rules as mechanics, scenario
from hoc.names import NameGenerator, peerage_title
from hoc.rules_data import load_rules, probability_for_age

__all__ = ["SimError", "LoggingRandom", "World", "RULES_VERSION"]

# The rules/CHANGELOG.md version these seasons are played under (§11): a season
# keeps the version it was played under so a later rules change never silently
# reinterprets it.
RULES_VERSION = "0.4"

STAT_RANGE = (0, 100)
AMBITION_RANGE = (0, 10)
TOTAL_RIDINGS = 343

# Actions PART A resolves. Anything else in rules/actions.csv is recognised —
# it stays in the table and in the loaded bundle — but is weighted zero until
# PART B implements it, so the engine never draws an action it cannot carry out.
IMPLEMENTED_ACTIONS = frozenset({
    # PART A: the expansion era.
    "Expand",
    "Invest",
    "Cultivate influence",
    "Name heir",
    "Endow",
    "Petition elevation",
    "Consolidate (rest)",
    # PART B: relations and the late game.
    "Correspond",
    "Propose compact",
    "Reconcile",
    "Dispute",
    "Challenge (11b)",
    "Purchase riding",
    "Marriage alliance",
    "Absorb",
    "Cede / swap",
    # Partition is never drawn from the pool — it is forced by a death (§9).
})

# The v1 relation glyphs, spelled exactly as the reconstructed record spells them
# (Sig− carries a real minus sign, not a hyphen), plus 'kin' from Phase 9c.
ACQUAINTED = "◎"
FRIENDLY = "+"
COMPACT = "◉+"
GRIEVANCE = "Sig−"
HOSTILE = "⊖"
CHALLENGED = "⚔"
RESOLVED = "~"
KIN = "kin"

# Which provinces touch which, for Correspond's "another house within 2
# provinces". Geography, not adjacency of ridings: PE is counted as touching NB
# and NS, and NL as touching QC through Labrador.
PROVINCE_NEIGHBOURS = {
    "NL": {"QC"},
    "PE": {"NB", "NS"},
    "NS": {"NB", "PE"},
    "NB": {"QC", "NS", "PE"},
    "QC": {"NL", "NB", "ON"},
    "ON": {"QC", "MB"},
    "MB": {"ON", "SK", "NU"},
    "SK": {"MB", "AB", "NT"},
    "AB": {"SK", "BC", "NT"},
    "BC": {"AB", "YT", "NT"},
    "YT": {"BC", "NT"},
    "NT": {"YT", "BC", "AB", "SK", "NU"},
    "NU": {"NT", "MB"},
}

CORRESPONDENCE_RANGE = 2

# §7b: a house that cannot grow outward grows upward.
ENCLOSURE_DOUBLED = frozenset({"Cultivate influence", "Endow", "Petition elevation"})

# How a response reads in the chronicle. "Neutral" has no verb of its own.
RESPONSE_VERB = {
    "Lead": "leads",
    "Resist": "resists",
    "Exploit": "exploits",
    "Neutral": "stands aside",
}

MAX_OBJECTIVES = 3
OBJECTIVES_AT_FOUNDING = 2
DEFEND_THE_SEAT_SEASONS = 3
SIEGE_SEASONS = 10

# How often the engine writes a stat snapshot for every living house. Five keeps
# a 300-season sparkline sixty points long and timeline.json well inside its
# size budget; hoc/export/timeline.py reads whatever spacing it finds.
SNAPSHOT_EVERY = 5


class SimError(Exception):
    """The engine cannot proceed: a malformed world, not a rules outcome."""


# ------------------------------------------------------------------- random --


def season_seed(world_seed, season_no):
    """A stable seed for one season.

    Python's built-in hash is salted per process for strings, so a world that
    hashed its own name would replay differently in a new process. Digesting the
    pair instead keeps replay honest across machines and Python versions.
    """
    digest = hashlib.blake2b(f"{world_seed}:{season_no}".encode("utf-8"), digest_size=8)
    return int.from_bytes(digest.digest(), "big")


class LoggingRandom:
    """A seeded RNG that records every draw it is asked for.

    Each call appends `{purpose, result}` to the season log, which is what makes
    a season auditable: the log says not only what happened but which roll made
    it happen.
    """

    def __init__(self, rng, log):
        self.rng = rng
        self.log = log
        self._purpose = "unattributed"

    def for_purpose(self, purpose):
        """A shallow view of this RNG that labels its draws. The underlying
        generator is shared, so the sequence is unaffected by the labelling."""
        view = LoggingRandom(self.rng, self.log)
        view._purpose = purpose
        return view

    def _record(self, purpose, result):
        self.log.append({"purpose": purpose or self._purpose, "result": result})
        return result

    def draw(self, purpose, result):
        """Record a value derived outside this class (a computed probability
        outcome, say) so it still appears in the log."""
        return self._record(purpose, result)

    def choice(self, sequence, purpose=None):
        return self._record(purpose, self.rng.choice(list(sequence)))

    def randint(self, low, high, purpose=None):
        return self._record(purpose, self.rng.randint(low, high))

    def random(self, purpose=None):
        return self._record(purpose, self.rng.random())

    def chance(self, probability, purpose=None):
        """True with the given probability. Logged as the roll and the verdict,
        because 'why did that house die' is the commonest question of a log."""
        roll = self.rng.random()
        return self._record(purpose, {"roll": round(roll, 6), "p": probability, "hit": roll < probability})["hit"]

    def die(self, sides=6, purpose=None):
        return self._record(purpose, self.rng.randint(1, sides))

    def two_d6(self, purpose=None):
        a = self.rng.randint(1, 6)
        b = self.rng.randint(1, 6)
        return self._record(purpose, {"dice": [a, b], "total": a + b})["total"]

    def weighted(self, options, purpose=None):
        """Draw from {key: weight}. Zero and negative weights never come up."""
        items = [(key, weight) for key, weight in options.items() if weight > 0]
        if not items:
            return self._record(purpose, None)
        total = sum(weight for _, weight in items)
        target = self.rng.random() * total
        running = 0.0
        chosen = items[-1][0]
        for key, weight in items:
            running += weight
            if target < running:
                chosen = key
                break
        return self._record(purpose, chosen)


def clamp(value, low, high):
    return max(low, min(high, value))


# -------------------------------------------------------------------- world --


class World:
    """One scenario, played by the engine against an open connection.

    Nothing here commits: the caller owns the transaction, exactly as the v1
    turn runner does, so a season that fails part-way leaves the database as it
    was.
    """

    def __init__(self, conn, rules=None, world_seed=None, seasons_dir=None):
        self.conn = conn
        self.rules = rules or load_rules()
        self.world_seed = world_seed if world_seed is not None else self._stored_seed()
        # Where season logs are written. None means "write nothing", which is what
        # a test world wants: a World must never infer its scenario from
        # scenarios/current.txt, or a run against a scratch database would drop
        # season files into whichever game happens to be active.
        self.seasons_dir = Path(seasons_dir) if seasons_dir is not None else None
        # Memoised answers to the expensive relational and adjacency questions.
        # Cleared before each house acts, so nothing survives a change that would
        # make it wrong; it only removes the repetition inside one house's turn,
        # where legal_actions and action_weights ask the same questions over.
        self._turn_cache = {}
        self._expansion_claims = {}
        self.log = []
        self.chronicle = []

        self.eras = sorted(self.rules.eras, key=lambda e: e.start_year)
        self.actions = {a.action: a for a in self.rules.actions}
        self.objectives = {o.objective: o for o in self.rules.objectives}
        self.communities_by_region = defaultdict(list)
        for community in self.rules.communities:
            self.communities_by_region[community.region].append(community)
        self.region_weights = dict(self.rules.founding["region_weights"]["initial"])
        self.rank_index = {
            rank: index
            for rank, index in self.rules.founding["rank_index"].items()
            if isinstance(index, int)
        }

    # -- persistence of the world seed --

    def _stored_seed(self):
        row = self.conn.execute(
            "SELECT seed FROM seasons ORDER BY season_no DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise SimError(
                "this world has no seed: run `python -m hoc sim new --seed N` first"
            )
        return row["seed"]

    @property
    def season_no(self):
        row = self.conn.execute("SELECT MAX(season_no) AS n FROM seasons").fetchone()
        return 0 if row is None or row["n"] is None else row["n"]

    # -- reading the world --

    def active_houses(self):
        """House rows in the fixed order §6 requires: by founding, then seat name."""
        return self.conn.execute(
            "SELECT h.house, h.rank, h.peerage, s.* FROM houses h"
            " JOIN house_stats s ON s.house = h.house"
            " LEFT JOIN holdings seat ON seat.house = h.house AND seat.seat_order = 1"
            "   AND seat.released_event_id IS NULL"
            " LEFT JOIN ridings r ON r.fed_id = seat.fed_id"
            " WHERE h.status = 'active'"
            " ORDER BY s.founded_season, r.name_en, h.house"
        ).fetchall()

    def house_row(self, house):
        row = self.conn.execute(
            "SELECT h.house, h.rank, h.peerage, h.status, s.*"
            " FROM houses h JOIN house_stats s ON s.house = h.house WHERE h.house = ?",
            (house,),
        ).fetchone()
        if row is None:
            raise SimError(f"unknown house {house!r}")
        return row

    def holder(self, house):
        return self.conn.execute(
            "SELECT * FROM persons WHERE house = ? AND role = 'holder' AND alive = 1",
            (house,),
        ).fetchone()

    def heirs(self, house):
        return self.conn.execute(
            "SELECT * FROM persons WHERE house = ? AND role IN ('heir', 'heir2')"
            " AND alive = 1 ORDER BY role",
            (house,),
        ).fetchall()

    def holdings(self, house):
        return self.conn.execute(
            "SELECT h.*, r.name_en, r.province FROM holdings h"
            " JOIN ridings r ON r.fed_id = h.fed_id"
            " WHERE h.house = ? AND h.released_event_id IS NULL"
            " ORDER BY h.seat_order",
            (house,),
        ).fetchall()

    def holding_count(self, house):
        return self.conn.execute(
            "SELECT COUNT(*) AS n FROM holdings WHERE house = ? AND released_event_id IS NULL",
            (house,),
        ).fetchone()["n"]

    def personal_year(self, house):
        row = self.conn.execute(
            "SELECT personal_year FROM clocks WHERE house = ?", (house,)
        ).fetchone()
        if row is None or row["personal_year"] is None:
            raise SimError(f"{house} has no personal year recorded")
        return row["personal_year"]

    def band_for(self, personal_year):
        """The era band a personal year sits in — the house's climate context."""
        for era in self.eras:
            if era.end_year is None or personal_year <= era.end_year:
                if personal_year >= era.start_year:
                    return era.id
        return self.eras[-1].id if personal_year >= self.eras[-1].start_year else self.eras[0].id

    def held_objectives(self, house):
        return [
            row["objective"]
            for row in self.conn.execute(
                "SELECT objective FROM objectives WHERE house = ?"
                " AND satisfied_season IS NULL ORDER BY id",
                (house,),
            )
        ]

    def unclaimed_land_adjacent_count(self):
        return self.conn.execute(
            "SELECT COUNT(*) AS n FROM ridings r"
            " WHERE NOT EXISTS (SELECT 1 FROM holdings h WHERE h.fed_id = r.fed_id"
            "                   AND h.released_event_id IS NULL)"
            "   AND EXISTS (SELECT 1 FROM adjacency a WHERE a.adjacency_type = 'land'"
            "               AND (a.fed_id_a = r.fed_id OR a.fed_id_b = r.fed_id))"
        ).fetchone()["n"]

    def has_expansion_target(self, house):
        """Whether any unclaimed riding touches this house — the enclosure test.

        Separate from expansion_targets because the answer is usually all that is
        wanted, and stopping at the first hit is far cheaper than collecting every
        target for ninety houses every season.
        """
        key = ("can_expand", house)
        if key not in self._turn_cache:
            row = self.conn.execute(
                "SELECT 1 FROM holdings mine"
                " JOIN adjacency a ON a.adjacency_type = 'land'"
                "   AND (a.fed_id_a = mine.fed_id OR a.fed_id_b = mine.fed_id)"
                " WHERE mine.house = ? AND mine.released_event_id IS NULL"
                "   AND NOT EXISTS (SELECT 1 FROM holdings h WHERE h.released_event_id IS NULL"
                "                   AND h.fed_id = CASE WHEN a.fed_id_a = mine.fed_id"
                "                                       THEN a.fed_id_b ELSE a.fed_id_a END)"
                " LIMIT 1",
                (house,),
            ).fetchone()
            self._turn_cache[key] = row is not None
        return self._turn_cache[key]

    def unenclosed_houses(self):
        """Every active house with somewhere left to expand into, in one query.

        The per-house version of this was the engine's single largest cost: a
        300-season run asked it twenty thousand times.
        """
        return {
            row["house"]
            for row in self.conn.execute(
                "SELECT DISTINCT mine.house FROM holdings mine"
                " JOIN houses h ON h.house = mine.house AND h.status = 'active'"
                " JOIN adjacency a ON a.adjacency_type = 'land'"
                "   AND (a.fed_id_a = mine.fed_id OR a.fed_id_b = mine.fed_id)"
                " WHERE mine.released_event_id IS NULL"
                "   AND NOT EXISTS (SELECT 1 FROM holdings o WHERE o.released_event_id IS NULL"
                "                   AND o.fed_id = CASE WHEN a.fed_id_a = mine.fed_id"
                "                                       THEN a.fed_id_b ELSE a.fed_id_a END)"
            )
        }

    def expansion_targets(self, house):
        """Unclaimed ridings land-adjacent to one of the house's holdings."""
        return [
            row["fed_id"]
            for row in self.conn.execute(
                "SELECT DISTINCT r.fed_id FROM ridings r"
                " JOIN adjacency a ON a.adjacency_type = 'land'"
                "   AND (a.fed_id_a = r.fed_id OR a.fed_id_b = r.fed_id)"
                " JOIN holdings mine ON mine.released_event_id IS NULL AND mine.house = ?"
                "   AND mine.fed_id = CASE WHEN a.fed_id_a = r.fed_id THEN a.fed_id_b ELSE a.fed_id_a END"
                " WHERE NOT EXISTS (SELECT 1 FROM holdings h WHERE h.fed_id = r.fed_id"
                "                   AND h.released_event_id IS NULL)"
                " ORDER BY r.fed_id",
                (house,),
            )
        ]

    def taken_places(self):
        """Territorial designations already carried by a living house, so a new
        peerage never reuses one (rules/README.md, Naming policy)."""
        return {
            row["seat_place"]
            for row in self.conn.execute(
                "SELECT s.seat_place FROM house_stats s JOIN houses h ON h.house = s.house"
                " WHERE h.status = 'active' AND s.seat_place IS NOT NULL"
            )
        }

    # -- writing --

    def set_stats(self, house, **deltas):
        """Apply stat deltas, clamped. Returns the row after the change.

        Clamping is deliberate and central: §4 puts every stat in 0-100 (ambition
        0-10), and the smoke test checks it, so no individual rule has to
        remember to bound its own arithmetic.
        """
        row = self.house_row(house)
        values = {}
        for stat in ("capital", "influence", "cohesion"):
            if stat in deltas:
                values[stat] = clamp(row[stat] + deltas[stat], *STAT_RANGE)
        if "ambition" in deltas:
            values["ambition"] = clamp(row["ambition"] + deltas["ambition"], *AMBITION_RANGE)
        if not values:
            return row
        assignments = ", ".join(f"{stat} = ?" for stat in values)
        self.conn.execute(
            f"UPDATE house_stats SET {assignments} WHERE house = ?",
            (*values.values(), house),
        )
        return self.house_row(house)

    def record(self, kind, title, houses, season, band=None, line=None, delta=None):
        """An engine event, with the season stamped into mechanical_delta.

        Events carry no season column in the v1 schema, and adding one would
        change a table the reconstructed game shares. The season lives in the
        JSON delta instead, which every engine event writes.
        """
        payload = {"season": season}
        if delta:
            payload.update(delta)
        event_id = mechanics.record_event(
            self.conn,
            kind=kind,
            title=title,
            houses=houses,
            era_cohort=band,
            narrative=line,
            mechanical_delta=payload,
            source="engine",
        )
        if line:
            self.chronicle.append(line)
        return event_id

    # -------------------------------------------------------------- founding --

    def _initial_climate(self):
        """Every band starts its ledger at zero. The ledgers are parallel and are
        never collapsed into one number (hard rule 8)."""
        for era in self.eras:
            existing = self.conn.execute(
                "SELECT 1 FROM climate WHERE era_cohort = ?", (era.id,)
            ).fetchone()
            if existing is None:
                self.conn.execute(
                    "INSERT INTO climate (era_cohort, seq, event, magnitude, tag,"
                    " cumulative_after, source) VALUES (?, 1, 'Season 0', NULL, NULL, '0', 'engine')",
                    (era.id,),
                )

    def _draw_region(self, rng):
        """Region weights drift toward whichever region still has unclaimed
        land-adjacent capacity, so settlement moves west as the east fills
        without any date driving it (§10)."""
        capacity = defaultdict(int)
        for row in self.conn.execute(
            "SELECT r.province, COUNT(*) AS n FROM ridings r"
            " WHERE NOT EXISTS (SELECT 1 FROM holdings h WHERE h.fed_id = r.fed_id"
            "                   AND h.released_event_id IS NULL)"
            " GROUP BY r.province"
        ):
            capacity[PROVINCE_REGION.get(row["province"], "north")] += row["n"]

        weights = {}
        for region, base in self.region_weights.items():
            room = capacity.get(region, 0)
            if room == 0:
                continue
            weights[region] = base * (1 + room / 20)
        if not weights:
            return None
        return rng.weighted(weights, purpose="founding.region")

    def _draw_seat(self, rng, region):
        """An unclaimed riding in the region. Weighted toward ridings that already
        have a claimed land neighbour once a region is settled, which is what
        'population centres early, hinterland later' amounts to on this map:
        houses cluster where houses already are."""
        provinces = [p for p, r in PROVINCE_REGION.items() if r == region]
        if not provinces:
            return None
        placeholders = ",".join("?" for _ in provinces)
        rows = self.conn.execute(
            f"SELECT r.fed_id, r.name_en, r.province FROM ridings r"
            f" WHERE r.province IN ({placeholders})"
            "   AND NOT EXISTS (SELECT 1 FROM holdings h WHERE h.fed_id = r.fed_id"
            "                   AND h.released_event_id IS NULL)"
            " ORDER BY r.fed_id",
            provinces,
        ).fetchall()
        if not rows:
            return None
        return rng.choice([row["fed_id"] for row in rows], purpose="founding.seat")

    def _draw_tag(self, rng):
        """Tag with climate fit: the Confederation ledger's sign doubles the
        weight of the matching tag (§10)."""
        weights = {"Progressive": 2.0, "Conservative": 2.0, "Mixed": 2.0, "Outside": 1.0}
        try:
            climate = mechanics.current_climate(self.conn, "confederation")
        except mechanics.RuleError:
            climate = 0
        if climate > 0:
            weights["Progressive"] *= 2
        elif climate < 0:
            weights["Conservative"] *= 2
        return rng.weighted(weights, purpose="founding.tag")

    def found_house(self, season, seat=None, rng=None, community=None, tag=None):
        """Found a house (§10 and §4). Returns its name, or None if it cannot.

        `seat` may be a riding name the director chose; otherwise the region and
        seat are drawn. Everything else — community, tag, rank, names, colours,
        stats, objectives — comes from the tables and the season's RNG.
        """
        rng = rng or self.rng_for(season)
        self._initial_climate()

        if seat is not None:
            fed_id = self._resolve_riding(seat)
            if fed_id is None:
                raise SimError(f"unknown riding {seat!r}")
            if mechanics._holder_of(self.conn, fed_id) is not None:
                raise SimError(f"riding {seat!r} is already held")
            province = self.conn.execute(
                "SELECT province FROM ridings WHERE fed_id = ?", (fed_id,)
            ).fetchone()["province"]
            region = PROVINCE_REGION.get(province, "north")
        else:
            region = self._draw_region(rng)
            if region is None:
                return None
            fed_id = self._draw_seat(rng, region)
            if fed_id is None:
                return None
            province = self.conn.execute(
                "SELECT province FROM ridings WHERE fed_id = ?", (fed_id,)
            ).fetchone()["province"]

        pool = self.communities_by_region.get(region) or self.communities_by_region["ontario"]
        if community is None:
            community_row = rng.weighted(
                {c.community: c.weight for c in pool}, purpose="founding.community"
            )
        else:
            community_row = community
        community_obj = next(
            (c for c in pool if c.community == community_row),
            next(c for c in self.rules.communities if c.community == community_row),
        )

        tag = tag or self._draw_tag(rng)
        rank = rng.weighted(self.rules.founding["rank_probabilities"], purpose="founding.rank")
        rank_index = self.rank_index.get(rank, 0)

        generator = NameGenerator(self.rules, rng)
        try:
            drawn = generator.draw_house(
                community_obj.community, province, rank, taken_places=self.taken_places()
            )
        except Exception as exc:  # a bank that cannot serve this province
            self.log.append({"purpose": "founding.abandoned", "result": str(exc)})
            return None

        house = self._unique_house_name(drawn["surname"])

        primaries = [
            row["primary_hex"]
            for row in self.conn.execute(
                "SELECT primary_hex FROM houses WHERE status = 'active' AND primary_hex IS NOT NULL"
            )
        ]
        primary, secondary = palette.assign_colours(primaries, rng.for_purpose("founding.colour"))

        self.conn.execute(
            "INSERT INTO houses (house, peerage, rank, status, primary_hex, secondary_hex, notes)"
            " VALUES (?, ?, ?, 'active', ?, ?, ?)",
            (house, drawn["peerage"], rank, primary, secondary, f"founded season {season}"),
        )

        stats = {
            "capital": clamp(30 + 5 * rank_index + rng.randint(1, 20, "founding.capital"), *STAT_RANGE),
            "influence": clamp(20 + 5 * rank_index + rng.randint(1, 20, "founding.influence"), *STAT_RANGE),
            "cohesion": clamp(60 + rng.randint(1, 20, "founding.cohesion"), *STAT_RANGE),
            "ambition": clamp(rng.randint(1, 10, "founding.ambition"), *AMBITION_RANGE),
        }
        self.conn.execute(
            "INSERT INTO house_stats (house, capital, influence, cohesion, ambition, enclosed,"
            " community, region, tradition, tag, province, seat_place, founded_season)"
            " VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)",
            (
                house,
                stats["capital"],
                stats["influence"],
                stats["cohesion"],
                stats["ambition"],
                community_obj.community,
                region,
                drawn["tradition"],
                tag,
                province,
                drawn["place"],
                season,
            ),
        )

        holder_age = 40 + rng.randint(1, 30, "founding.holder_age")
        self.conn.execute(
            "INSERT INTO persons (house, name, gender, age, role, alive, born_season)"
            " VALUES (?, ?, ?, ?, 'holder', 1, ?)",
            (house, f"{drawn['given']} {drawn['surname']}", drawn["gender"], holder_age, season),
        )
        self.conn.execute(
            "INSERT INTO clocks (house, personal_year, basis) VALUES (?, 1867, ?)",
            (house, f"founded season {season}"),
        )

        event_id = self.record(
            "founding",
            f"{drawn['peerage']} founded",
            [house],
            season,
            band="confederation",
            line=f"Season {season} · {drawn['peerage']} is created, seated at "
                 f"{self._riding_name(fed_id)}.",
            delta={"stats": stats, "community": community_obj.community, "tag": tag},
        )
        self.conn.execute(
            "INSERT INTO holdings (house, fed_id, seat_order, hex, acquired_event_id)"
            " VALUES (?, ?, 1, ?, ?)",
            (house, fed_id, primary, event_id),
        )

        self._draw_founding_objectives(house, season, rng)
        return house

    def _draw_founding_objectives(self, house, season, rng):
        row = self.house_row(house)
        weights = {}
        for objective in self.rules.objectives:
            weights[objective.objective] = 1.0 + 2.0 * self._objective_favoured(objective.objective, row, house)
        for _ in range(OBJECTIVES_AT_FOUNDING):
            held = set(self.held_objectives(house))
            available = {k: v for k, v in weights.items() if k not in held}
            if not available:
                break
            chosen = rng.weighted(available, purpose="founding.objective")
            self.conn.execute(
                "INSERT INTO objectives (house, objective, acquired_season) VALUES (?, ?, ?)",
                (house, chosen, season),
            )

    def _objective_favoured(self, objective, row, house):
        """§5's 'favoured by' column, as a 0/1 test. Objectives whose trigger
        belongs to PART B (relations) are never favoured yet, which keeps them
        rare rather than pretending they can be satisfied."""
        holder = self.holder(house)
        holdings = self.holding_count(house)
        if objective == "Consolidate region":
            return 1 if holdings <= 2 else 0
        if objective == "Secure succession":
            return 1 if holder is not None and holder["age"] >= 60 and not self.heirs(house) else 0
        if objective == "Seek elevation":
            return 1 if row["influence"] >= 60 else 0
        if objective == "Endow an institution":
            return 1 if row["capital"] >= 70 else 0
        if objective == "Form a compact":
            return 1 if row["tag"] in ("Progressive", "Mixed") else 0
        return 0

    def _unique_house_name(self, surname):
        """House names are surnames; a second house of the same surname takes a
        numeral, as the v1 record did for cadet lines."""
        existing = {
            row["house"] for row in self.conn.execute("SELECT house FROM houses")
        }
        if surname not in existing:
            return surname
        for suffix in range(2, 100):
            candidate = f"{surname} {suffix}"
            if candidate not in existing:
                return candidate
        raise SimError(f"cannot make a unique house name from {surname!r}")

    def _resolve_riding(self, name):
        from hoc.names import name_key

        row = self.conn.execute(
            "SELECT fed_id FROM ridings WHERE name_key = ?", (name_key(name),)
        ).fetchone()
        return None if row is None else row["fed_id"]

    def _riding_name(self, fed_id):
        row = self.conn.execute(
            "SELECT name_en FROM ridings WHERE fed_id = ?", (fed_id,)
        ).fetchone()
        return row["name_en"] if row else fed_id

    # ------------------------------------------------------------- mortality --

    def _age_everyone(self, season):
        self.conn.execute("UPDATE persons SET age = age + 1 WHERE alive = 1")
        self.conn.execute(
            "UPDATE clocks SET personal_year = personal_year + 1 WHERE house IN"
            " (SELECT house FROM houses WHERE status = 'active')"
        )

    def _mortality(self, house, season, rng, extra_roll=False):
        """§9. Returns True if the house was removed."""
        holder = self.holder(house)
        if holder is None:
            return self._succeed(house, season, rng, cause="no holder")

        probability = probability_for_age(self.rules.mortality, holder["age"])
        rolls = 2 if extra_roll else 1
        died = any(
            rng.chance(probability, purpose=f"mortality.{house}") for _ in range(rolls)
        )
        if not died:
            return False

        self.conn.execute(
            "UPDATE persons SET alive = 0, died_season = ? WHERE id = ?", (season, holder["id"])
        )
        return self._succeed(house, season, rng, cause="death")

    def _succeed(self, house, season, rng, cause):
        """Clean, disorderly or extinct (§9). Returns True if removed."""
        row = self.house_row(house)
        heirs = self.heirs(house)
        band = self.band_for(self.personal_year(house))

        if heirs:
            heir = heirs[0]
            self.conn.execute(
                "UPDATE persons SET role = 'holder' WHERE id = ?", (heir["id"],)
            )
            # §9: two named heirs and four holdings partition the house — this is
            # how the map's later seasons fill with related houses.
            partitioned = None
            spec = self.rules.succession["partition"]
            if (
                len(heirs) >= spec["min_heirs"]
                and self.holding_count(house) >= spec["min_holdings"]
            ):
                partitioned = self._partition(house, heirs[1], season, rng, band)
            for spare in heirs[1:]:
                if partitioned is None or spare["id"] != heirs[1]["id"]:
                    self.conn.execute(
                        "UPDATE persons SET role = 'other' WHERE id = ?", (spare["id"],)
                    )
            self.set_stats(house, cohesion=self.rules.succession["clean_succession"]["cohesion_delta"])
            self.conn.execute(
                "UPDATE clocks SET personal_year = 1867, basis = ? WHERE house = ?",
                (f"reset at accession, season {season}", house),
            )
            self.record(
                "succession",
                f"{row['peerage']}: clean succession",
                [house],
                season,
                band=band,
                line=f"Season {season} · {heir['name']} succeeds to {row['peerage']}.",
                delta={"nature": "clean", "cause": cause},
            )
            return self._check_extinction(house, season, rng)

        # Disorderly: no heir named.
        succession = self.rules.succession["disorderly_succession"]
        self.set_stats(
            house,
            cohesion=succession["cohesion_delta"],
            capital=succession["capital_delta"],
        )
        if rng.chance(0.20, purpose=f"succession.no_successor.{house}"):
            self._remove_house(house, season, reason="no successor", rng=rng)
            return True

        community = row["community"]
        generator = NameGenerator(self.rules, rng)
        given, surname, gender = generator.draw_person(community, surname=house.split(" ")[0])
        age = 35 + rng.randint(1, 20, "succession.successor_age")
        self.conn.execute(
            "INSERT INTO persons (house, name, gender, age, role, alive, born_season)"
            " VALUES (?, ?, ?, ?, 'holder', 1, ?)",
            (house, f"{given} {surname}", gender, age, season),
        )
        self.conn.execute(
            "UPDATE clocks SET personal_year = 1867, basis = ? WHERE house = ?",
            (f"reset at disorderly accession, season {season}", house),
        )
        self.record(
            "succession",
            f"{row['peerage']}: disorderly succession",
            [house],
            season,
            band=band,
            line=f"Season {season} · {row['peerage']} passes in disorder to {given} {surname}.",
            delta={"nature": "disorderly", "cause": cause},
        )

        # §9: a disorderly succession sours a neighbour.
        neighbours = self.neighbouring_houses(house)
        probability = self.rules.succession["disorderly_succession"]["sig_minus_probability"]
        if neighbours and rng.chance(probability, purpose=f"succession.grievance.{house}"):
            other = rng.choice(neighbours, purpose=f"succession.grievance_with.{house}")
            if self.relation_marker(house, other) not in (KIN, COMPACT):
                grievance_id = self.record(
                    "relational",
                    f"{row['peerage']} falls out with {self.house_row(other)['peerage']}",
                    [house, other],
                    season,
                    band=band,
                    delta={"marker": GRIEVANCE, "cause": "disorderly succession"},
                )
                self.set_relation(house, other, GRIEVANCE, grievance_id, "disorderly succession")

        # §7c: contested wills and Crown review can cost a riding.
        loss = self.rules.succession["losing_ridings"]["disorderly_succession"]
        if self.holding_count(house) >= 4 and rng.chance(
            loss["probability"], purpose=f"succession.riding_loss.{house}"
        ):
            self._lose_riding(house, season, reason="disorderly succession")

        return self._check_extinction(house, season, rng)


    def _partition(self, house, junior, season, rng, band):
        """The junior heir founds a cadet house in the outer holdings (§9).

        The senior keeps the seat and the core around it; the cadet takes what
        lies furthest from the seat, which is what "outer holdings" means on a
        map — the parent's reach thins at its edge and a new house forms there.
        """
        row = self.house_row(house)
        holdings = self.holdings(house)
        if len(holdings) < self.rules.succession["partition"]["min_holdings"]:
            return None

        outer = self._outer_holdings(house, holdings)
        if not outer:
            return None

        cadet = self._unique_house_name(house.split(" ")[0])
        primaries = [
            r["primary_hex"]
            for r in self.conn.execute(
                "SELECT primary_hex FROM houses WHERE status = 'active' AND primary_hex IS NOT NULL"
            )
        ]
        primary, secondary = palette.assign_colours(primaries, rng.for_purpose("partition.colour"))

        province = self.conn.execute(
            "SELECT province FROM ridings WHERE fed_id = ?", (outer[0]["fed_id"],)
        ).fetchone()["province"]
        generator = NameGenerator(self.rules, rng)
        try:
            place = generator.draw_place(province, self.taken_places())
        except Exception:
            return None
        peerage = peerage_title("Baron", house.split(" ")[0], place, row["tradition"])

        self.conn.execute(
            "INSERT INTO houses (house, peerage, rank, status, primary_hex, secondary_hex, notes)"
            " VALUES (?, ?, 'Baron', 'active', ?, ?, ?)",
            (cadet, peerage, primary, secondary, f"cadet of {house}, season {season}"),
        )
        self.conn.execute(
            "INSERT INTO house_stats (house, capital, influence, cohesion, ambition, enclosed,"
            " community, region, tradition, tag, province, seat_place, founded_season)"
            " VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)",
            (
                cadet,
                max(0, row["capital"] // 2),
                max(0, row["influence"] // 2),
                clamp(60 + rng.randint(1, 20, "partition.cohesion"), *STAT_RANGE),
                row["ambition"],
                row["community"],
                row["region"],
                row["tradition"],
                row["tag"],
                province,
                place,
                season,
            ),
        )
        self.conn.execute(
            "UPDATE persons SET house = ?, role = 'holder' WHERE id = ?", (cadet, junior["id"])
        )
        self.conn.execute(
            "INSERT INTO clocks (house, personal_year, basis) VALUES (?, 1867, ?)",
            (cadet, f"cadet founding by partition, season {season}"),
        )

        event_id = self.record(
            "founding",
            f"{peerage} founded by partition from {row['peerage']}",
            [house, cadet],
            season,
            band=band,
            line=f"Season {season} · {peerage} is founded by partition from {row['peerage']}.",
            delta={"nature": "partition", "parent": house},
        )
        for holding in outer:
            self.conn.execute(
                "UPDATE holdings SET released_event_id = ? WHERE id = ?",
                (event_id, holding["id"]),
            )
        for order, holding in enumerate(outer, start=1):
            self.conn.execute(
                "INSERT INTO holdings (house, fed_id, seat_order, hex, acquired_event_id)"
                " VALUES (?, ?, ?, ?, ?)",
                (cadet, holding["fed_id"], order, primary if order == 1 else secondary, event_id),
            )
        self.set_relation(house, cadet, KIN, event_id, "cadet line")
        self._draw_founding_objectives(cadet, season, rng)
        # The parent keeps the seat; its remaining holdings renumber from 1.
        self._renumber(house)
        return cadet

    def _outer_holdings(self, house, holdings):
        """The half of the holdings furthest from the seat, by land steps."""
        seat = holdings[0]
        fed_ids = [h["fed_id"] for h in holdings]
        held = set(fed_ids)
        edges = defaultdict(set)
        placeholders = ",".join("?" for _ in fed_ids)
        for row in self.conn.execute(
            f"SELECT fed_id_a, fed_id_b FROM adjacency WHERE adjacency_type = 'land'"
            f" AND fed_id_a IN ({placeholders}) AND fed_id_b IN ({placeholders})",
            fed_ids + fed_ids,
        ):
            edges[row["fed_id_a"]].add(row["fed_id_b"])
            edges[row["fed_id_b"]].add(row["fed_id_a"])

        distance = {seat["fed_id"]: 0}
        frontier = [seat["fed_id"]]
        while frontier:
            nxt = []
            for node in frontier:
                for neighbour in edges[node] & held:
                    if neighbour not in distance:
                        distance[neighbour] = distance[node] + 1
                        nxt.append(neighbour)
            frontier = nxt

        # Anything unreachable from the seat is as outer as it gets.
        ranked = sorted(
            (h for h in holdings if h["fed_id"] != seat["fed_id"]),
            key=lambda h: (-distance.get(h["fed_id"], 10_000), h["fed_id"]),
        )
        return ranked[: max(1, len(ranked) // 2)]

    def _renumber(self, house):
        """Close the gaps seat_order leaves when holdings depart, keeping the
        principal seat first — the primary colour follows it (hard rule 4)."""
        rows = self.conn.execute(
            "SELECT id FROM holdings WHERE house = ? AND released_event_id IS NULL"
            " ORDER BY seat_order, id",
            (house,),
        ).fetchall()
        # Move them out of the way first: seat_order is uniquely indexed per house.
        for offset, row in enumerate(rows, start=1):
            self.conn.execute(
                "UPDATE holdings SET seat_order = ? WHERE id = ?", (-offset, row["id"])
            )
        for order, row in enumerate(rows, start=1):
            self.conn.execute(
                "UPDATE holdings SET seat_order = ? WHERE id = ?", (order, row["id"])
            )

    def _check_extinction(self, house, season, rng):
        row = self.house_row(house)
        if row["cohesion"] < 15:
            self._remove_house(house, season, reason="cohesion collapse", rng=rng)
            return True
        return False

    def _remove_house(self, house, season, reason, rng=None):
        """Extinction (§9): a ◉+ or kin partner may absorb the holdings at +3;
        otherwise they escheat to unclaimed. Either way the house stays in the
        record with its full history."""
        row = self.house_row(house)
        band = self.band_for(self.personal_year(house))

        if rng is not None:
            partners = self.houses_related_by(house, {COMPACT, KIN})
            if partners:
                heir_house = rng.choice(partners, purpose=f"extinction.absorber.{house}")
                if rng.two_d6(purpose=f"extinction.absorb_roll.{house}") + 3 >= 8:
                    self._absorb_into(heir_house, house, season, band, reason=f"escheat: {reason}")
                    return
        event_id = self.record(
            "succession",
            f"{row['peerage']} extinct",
            [house],
            season,
            band=band,
            line=f"Season {season} · {row['peerage']} fails; its ridings return to the Crown.",
            delta={"nature": "extinction", "reason": reason},
        )
        self.conn.execute(
            "UPDATE holdings SET released_event_id = ? WHERE house = ? AND released_event_id IS NULL",
            (event_id, house),
        )
        self.conn.execute("UPDATE houses SET status = 'removed' WHERE house = ?", (house,))
        self.conn.execute(
            "UPDATE house_stats SET removed_season = ? WHERE house = ?", (season, house)
        )
        self.conn.execute(
            "UPDATE persons SET alive = 0, died_season = ? WHERE house = ? AND alive = 1",
            (season, house),
        )

    def _lose_riding(self, house, season, reason, to_house=None):
        """Lose the most recently acquired non-seat riding (§7c). The seat is
        only ever lost by challenge, absorption or extinction."""
        rows = self.conn.execute(
            "SELECT * FROM holdings WHERE house = ? AND released_event_id IS NULL"
            " AND seat_order > 1 ORDER BY id DESC LIMIT 1",
            (house,),
        ).fetchall()
        if not rows:
            return None
        holding = rows[0]
        row = self.house_row(house)
        band = self.band_for(self.personal_year(house))
        name = self._riding_name(holding["fed_id"])
        houses = [house] if to_house is None else [house, to_house]
        event_id = self.record(
            "transfer",
            f"{row['peerage']} loses {name}",
            houses,
            season,
            band=band,
            line=f"Season {season} · {row['peerage']} gives up {name} ({reason}).",
            delta={"reason": reason, "riding": name},
        )
        self.conn.execute(
            "UPDATE holdings SET released_event_id = ? WHERE id = ?", (event_id, holding["id"])
        )
        if to_house is not None:
            self.conn.execute(
                "INSERT INTO holdings (house, fed_id, seat_order, hex, acquired_event_id)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    to_house,
                    holding["fed_id"],
                    mechanics._next_seat_order(self.conn, to_house),
                    mechanics._expansion_hex(self.conn, to_house),
                    event_id,
                ),
            )
        return holding["fed_id"]

    # ---------------------------------------------------------- era events --

    def _fired_events(self, house):
        rows = self.conn.execute(
            "SELECT e.title FROM events e JOIN event_houses eh ON eh.event_id = e.id"
            " WHERE eh.house = ? AND e.kind = 'societal'",
            (house,),
        )
        return {row["title"] for row in rows}

    def _era_event(self, house, season, rng):
        """§8. An event fires when the house's personal year equals its year, at
        most once per house. Returns the event row that fired, or None."""
        year = self.personal_year(house)
        due = [e for e in self.rules.events if e.personal_year == year]
        if not due:
            return None

        already = self._fired_events(house)
        due = [e for e in due if e.name not in already]
        if not due:
            return None

        if len(due) == 1:
            event = due[0]
        else:
            # Log the name, not the row: a season log has to stay JSON.
            name = rng.choice([e.name for e in due], purpose=f"event.pick.{house}")
            event = next(e for e in due if e.name == name)
        row = self.house_row(house)
        band = self.band_for(year)

        modifier = 0
        if row["tag"] == event.tag:
            modifier = self.rules.responses["tag_modifier"]["matching_tag"]
        elif self._opposing(row["tag"], event.tag):
            modifier = self.rules.responses["tag_modifier"]["opposing_tag"]
        roll = rng.die(6, purpose=f"event.response.{house}") + modifier
        response = self._response_for(roll)

        deltas = {}
        if response == "Lead":
            deltas = {"influence": 5}
            self._shift_climate(band, event, +1)
        elif response == "Resist":
            deltas = {"cohesion": 5}
            self._shift_climate(band, event, -1)
        elif response == "Exploit":
            deltas = {"capital": 10, "influence": -5}
        if deltas:
            self.set_stats(house, **deltas)

        extra_mortality = self._apply_direct_effects(house, event, season)

        self.record(
            "societal",
            event.name,
            [house],
            season,
            band=band,
            line=f"Season {season} · {row['peerage']} meets {event.name}"
                 f" and {RESPONSE_VERB[response]}.",
            delta={"response": response, "roll": roll, "personal_year": year,
                   "magnitude": event.magnitude, "tag": event.tag},
        )
        return {"event": event, "response": response, "extra_mortality": extra_mortality}

    @staticmethod
    def _opposing(house_tag, event_tag):
        pairs = {("Progressive", "Conservative"), ("Conservative", "Progressive")}
        return (house_tag, event_tag) in pairs

    def _response_for(self, roll):
        """d6 + tag modifier, split across the four options in §8's order."""
        if roll >= 6:
            return "Lead"
        if roll >= 4:
            return "Exploit"
        if roll >= 2:
            return "Resist"
        return "Neutral"

    def _shift_climate(self, band, event, direction):
        """Lead moves the band ledger one step toward the event's tag, Resist one
        against. A Global or Mixed event has no partisan direction to move."""
        signs = {"Progressive": 1, "Conservative": -1}
        sign = signs.get(event.tag)
        if sign is None:
            return
        try:
            mechanics.climate_shift(
                self.conn, band, event.name, event.magnitude,
                event.tag if event.tag in mechanics.CLIMATE_TAGS else "Mixed",
                sign * direction,
            )
        except mechanics.RuleError:
            pass

    def _in_scope(self, house_row, scope):
        """Does a direct effect's scope cover this house? (rules/README.md)"""
        if scope == "all":
            return True
        if scope == house_row["region"]:
            return True
        if scope == "newfoundland":
            return house_row["province"] == "NL"
        if scope == house_row["tag"]:
            return True
        groups = {
            "asian": {"Chinese", "Japanese", "Punjabi Sikh"},
            "francophone": {
                "Canadien Catholic", "Acadian", "Franco-Ontarian",
                "French-Canadian Prairie", "Métis",
            },
            "metis": {"Métis"},
        }
        if scope in groups:
            return house_row["community"] in groups[scope]
        if scope == "female_line":
            holder = self.holder(house_row["house"])
            return holder is not None and holder["gender"] == "f"
        return False

    def _apply_direct_effects(self, house, event, season):
        """A Major event's direct effects, by scope. Returns True if the house
        owes an extra mortality roll this season."""
        row = self.house_row(house)
        extra = False
        deltas = defaultdict(int)
        for effect in event.direct_effect:
            if not self._in_scope(row, effect.scope):
                continue
            if effect.stat == "mortality":
                extra = True
            else:
                deltas[effect.stat] += effect.delta
        if deltas:
            self.set_stats(house, **deltas)

        # §7c contraction sale: a Major Conservative economic event forces a poor
        # house to sell. The deck marks those with a negative capital effect.
        if (
            event.magnitude == "Major"
            and event.tag == "Conservative"
            and any(e.stat == "capital" and e.delta < 0 for e in event.direct_effect)
            and self.house_row(house)["capital"] < 20
        ):
            self._sell_riding(house, season, reason="contraction sale")
        return extra

    def _sell_riding(self, house, season, reason):
        """A forced sale: to an adjacent house with capital >= 50 if one exists,
        otherwise to the Crown (§7c)."""
        buyer = self.conn.execute(
            "SELECT s.house FROM house_stats s"
            " JOIN houses h ON h.house = s.house AND h.status = 'active'"
            " WHERE s.capital >= 50 AND s.house <> ?"
            "   AND EXISTS (SELECT 1 FROM holdings mine"
            "               JOIN adjacency a ON a.adjacency_type = 'land'"
            "                 AND (a.fed_id_a = mine.fed_id OR a.fed_id_b = mine.fed_id)"
            "               JOIN holdings theirs ON theirs.released_event_id IS NULL"
            "                 AND theirs.house = s.house"
            "                 AND theirs.fed_id = CASE WHEN a.fed_id_a = mine.fed_id"
            "                                          THEN a.fed_id_b ELSE a.fed_id_a END"
            "               WHERE mine.house = ? AND mine.released_event_id IS NULL)"
            " ORDER BY s.capital DESC, s.house LIMIT 1",
            (house, house),
        ).fetchone()
        to_house = buyer["house"] if buyer else None
        lost = self._lose_riding(house, season, reason=reason, to_house=to_house)
        if lost is not None and to_house is not None:
            self.set_stats(house, capital=30)
            self.set_stats(to_house, capital=-40)
        return lost


    # ------------------------------------------------------------ relations --
    #
    # A relation is an unordered pair, so it is always stored with the names in
    # sorted order and there is at most one row per pair. The marker is the v1
    # glyph vocabulary; changing a relation rewrites the row rather than adding
    # a second one, and the event log keeps the history.

    @staticmethod
    def _pair(house_a, house_b):
        return tuple(sorted((house_a, house_b)))

    def relation(self, house_a, house_b):
        low, high = self._pair(house_a, house_b)
        return self.conn.execute(
            "SELECT * FROM relations WHERE house_a = ? AND house_b = ?", (low, high)
        ).fetchone()

    def relation_marker(self, house_a, house_b):
        row = self.relation(house_a, house_b)
        return None if row is None else row["marker"]

    def set_relation(self, house_a, house_b, marker, event_id=None, text=None):
        low, high = self._pair(house_a, house_b)
        existing = self.relation(low, high)
        if existing is None:
            self.conn.execute(
                "INSERT INTO relations (house_a, house_b, marker, event_id, event_text, source)"
                " VALUES (?, ?, ?, ?, ?, 'engine')",
                (low, high, marker, event_id, text),
            )
        else:
            self.conn.execute(
                "UPDATE relations SET marker = ?, event_id = ?, event_text = ? WHERE id = ?",
                (marker, event_id, text, existing["id"]),
            )

    def houses_related_by(self, house, markers):
        """Active houses standing in one of these relations to this one."""
        key = ("related", house)
        if key not in self._turn_cache:
            self._turn_cache[key] = [
                (row["marker"], row["house_b"] if row["house_a"] == house else row["house_a"])
                for row in self.conn.execute(
                    "SELECT r.house_a, r.house_b, r.marker FROM relations r"
                    " JOIN houses other ON other.status = 'active' AND other.house ="
                    "   CASE WHEN r.house_a = ? THEN r.house_b ELSE r.house_a END"
                    " WHERE r.house_a = ? OR r.house_b = ?",
                    (house, house, house),
                )
            ]
        return sorted(other for marker, other in self._turn_cache[key] if marker in markers)

    def _relation_season(self, house_a, house_b):
        """When the current relation was last set, from the event it hangs off."""
        row = self.relation(house_a, house_b)
        if row is None or row["event_id"] is None:
            return None
        event = self.conn.execute(
            "SELECT mechanical_delta FROM events WHERE id = ?", (row["event_id"],)
        ).fetchone()
        try:
            return json.loads(event["mechanical_delta"])["season"]
        except (TypeError, ValueError, KeyError):
            return None

    def _dispute_blocked(self, house_a, house_b, season):
        """Marriage blocks disputes between two houses for a stretch of seasons
        (§7). Kin made by partition blocks them for the same stretch."""
        if self.relation_marker(house_a, house_b) != KIN:
            return False
        made = self._relation_season(house_a, house_b)
        if made is None:
            return True
        window = self.rules.succession["marriage_alliance"]["dispute_block_seasons"]
        return (season - made) < window

    @staticmethod
    @lru_cache(maxsize=None)
    def _province_distance(province_a, province_b):
        """Steps between two provinces, or None beyond the correspondence range.
        Pure geography, so it is computed once for the life of the process."""
        if province_a == province_b:
            return 0
        seen = {province_a}
        frontier = [province_a]
        for step in range(1, CORRESPONDENCE_RANGE + 1):
            nxt = []
            for province in frontier:
                for neighbour in PROVINCE_NEIGHBOURS.get(province, ()):
                    if neighbour in seen:
                        continue
                    if neighbour == province_b:
                        return step
                    seen.add(neighbour)
                    nxt.append(neighbour)
            frontier = nxt
        return None

    def province_distance(self, province_a, province_b):
        """Steps between two provinces, or None beyond the correspondence range."""
        return World._province_distance(province_a, province_b)

    def _profiles(self):
        """house -> the facts that never change after founding (province, tag).

        Cached for the whole turn: asking the database for ninety houses' tags
        once per weight calculation was the single most expensive thing the
        engine did.
        """
        if "profiles" not in self._turn_cache:
            self._turn_cache["profiles"] = {
                row["house"]: (row["province"], row["tag"])
                for row in self.conn.execute(
                    "SELECT s.house, s.province, s.tag FROM house_stats s"
                    " JOIN houses h ON h.house = s.house AND h.status = 'active'"
                )
            }
        return self._turn_cache["profiles"]

    def houses_within_reach(self, house):
        key = ("reach", house)
        if key not in self._turn_cache:
            profiles = self._profiles()
            mine = profiles.get(house)
            out = []
            if mine is not None:
                for other, (province, _) in profiles.items():
                    if other == house:
                        continue
                    distance = self.province_distance(mine[0], province)
                    if distance is not None and distance <= CORRESPONDENCE_RANGE:
                        out.append(other)
            self._turn_cache[key] = sorted(out)
        return self._turn_cache[key]

    def neighbouring_houses(self, house):
        """Houses holding a riding land-adjacent to one of this house's."""
        key = ("neighbours", house)
        if key in self._turn_cache:
            return self._turn_cache[key]
        result = [
            row["house"]
            for row in self.conn.execute(
                "SELECT DISTINCT theirs.house FROM holdings mine"
                " JOIN adjacency a ON a.adjacency_type = 'land'"
                "   AND (a.fed_id_a = mine.fed_id OR a.fed_id_b = mine.fed_id)"
                " JOIN holdings theirs ON theirs.released_event_id IS NULL"
                "   AND theirs.fed_id = CASE WHEN a.fed_id_a = mine.fed_id"
                "                            THEN a.fed_id_b ELSE a.fed_id_a END"
                " JOIN houses h ON h.house = theirs.house AND h.status = 'active'"
                " WHERE mine.house = ? AND mine.released_event_id IS NULL"
                "   AND theirs.house <> ?"
                " ORDER BY theirs.house",
                (house, house),
            )
        ]
        self._turn_cache[key] = result
        return result

    def _adjacent_holding_of(self, house, other):
        """A riding `other` holds that touches one of `house`'s, seat last: the
        seat is only ever lost by challenge, absorption or extinction (§7c), so
        anything else is a better target."""
        key = ("adjacent", house, other)
        if key in self._turn_cache:
            return self._turn_cache[key]
        rows = self.conn.execute(
            "SELECT DISTINCT theirs.fed_id, theirs.seat_order FROM holdings mine"
            " JOIN adjacency a ON a.adjacency_type = 'land'"
            "   AND (a.fed_id_a = mine.fed_id OR a.fed_id_b = mine.fed_id)"
            " JOIN holdings theirs ON theirs.released_event_id IS NULL"
            "   AND theirs.house = ?"
            "   AND theirs.fed_id = CASE WHEN a.fed_id_a = mine.fed_id"
            "                            THEN a.fed_id_b ELSE a.fed_id_a END"
            " WHERE mine.house = ? AND mine.released_event_id IS NULL"
            " ORDER BY CASE WHEN theirs.seat_order = 1 THEN 1 ELSE 0 END, theirs.fed_id",
            (other, house),
        ).fetchall()
        self._turn_cache[key] = None if not rows else rows[0]["fed_id"]
        return self._turn_cache[key]

    def _unmarried_heir(self, house):
        """An heir free to marry. §7 needs one on both sides of an alliance, and
        an heir only marries once — without the flag a single heir would bind
        their house to every neighbour in reach."""
        for heir in self.heirs(house):
            if not heir["married"]:
                return heir
        return None


    # ------------------------------------------------------------- friction --
    #
    # Grievance had to come from somewhere. Through PART B the only source of a
    # Sig− was a disorderly succession, so borders stayed quiet and the game ran
    # overwhelmingly cooperative. Friction (rules/friction.json, rules 0.6) is
    # the slow pressure between two houses that share a land border: it builds
    # while their tags oppose, while either is boxed in or ambitious, and it
    # cools while they are bound by friendship or marriage.

    def bordering_pairs(self):
        """Every unordered pair of active houses sharing a land border, once."""
        return [
            (row["a"], row["b"])
            for row in self.conn.execute(
                "SELECT DISTINCT MIN(mine.house, theirs.house) AS a,"
                "                MAX(mine.house, theirs.house) AS b"
                " FROM holdings mine"
                " JOIN adjacency adj ON adj.adjacency_type = 'land'"
                "   AND (adj.fed_id_a = mine.fed_id OR adj.fed_id_b = mine.fed_id)"
                " JOIN holdings theirs ON theirs.released_event_id IS NULL"
                "   AND theirs.fed_id = CASE WHEN adj.fed_id_a = mine.fed_id"
                "                            THEN adj.fed_id_b ELSE adj.fed_id_a END"
                " JOIN houses ha ON ha.house = mine.house AND ha.status = 'active'"
                " JOIN houses hb ON hb.house = theirs.house AND hb.status = 'active'"
                " WHERE mine.released_event_id IS NULL AND mine.house <> theirs.house"
                " ORDER BY a, b"
            )
        ]

    def friction_between(self, house_a, house_b):
        low, high = self._pair(house_a, house_b)
        row = self.conn.execute(
            "SELECT value FROM friction WHERE house_a = ? AND house_b = ?", (low, high)
        ).fetchone()
        return 0 if row is None else row["value"]

    def _set_friction(self, house_a, house_b, value):
        low, high = self._pair(house_a, house_b)
        bounds = self.rules.friction["range"]
        value = clamp(value, bounds[0], bounds[1])
        self.conn.execute(
            "INSERT INTO friction (house_a, house_b, value) VALUES (?, ?, ?)"
            " ON CONFLICT(house_a, house_b) DO UPDATE SET value = excluded.value",
            (low, high, value),
        )
        return value

    def _friction_delta(self, row_a, row_b, marker):
        """One season's movement on one border, from rules/friction.json."""
        spec = self.rules.friction["per_season"]

        # Friction is pressure that has not yet found an outlet. A pair already
        # standing in a grievance has found one, so their border holds where it
        # is until the quarrel is settled — otherwise the same two houses fall
        # out again every ten seasons and the map fills with recurring feuds.
        if marker in (GRIEVANCE, HOSTILE):
            return spec["open_quarrel"]["value"]

        tags = {row_a["tag"], row_b["tag"]}
        delta = 0
        moved = False

        if tags == {"Progressive", "Conservative"}:
            delta += spec["opposed_tags"]["value"]
            moved = True
        if row_a["enclosed"] or row_b["enclosed"]:
            delta += spec["either_enclosed"]["value"]
            moved = True
        if row_a["ambition"] >= 7 or row_b["ambition"] >= 7:
            delta += spec["high_ambition"]["value"]
            moved = True
        if marker in (FRIENDLY, COMPACT, KIN):
            delta += spec["bound"]["value"]
            moved = True

        if not moved:
            delta += spec["decay"]["value"]
        return delta

    def _grievance_template(self, row_a, row_b, rng):
        templates = self.rules.friction["grievances"]
        key = "|".join(sorted((row_a["tag"] or "Mixed", row_b["tag"] or "Mixed")))
        options = templates.get(key) or templates["default"]
        return rng.choice(options, purpose="friction.grievance")

    def _lapse_grievances(self, season):
        """A grievance nobody has pressed for long enough stops being one.

        Without this the map's stock of open Sig− relations only grows: every
        flashpoint adds one and only a dispute, reconciliation or cession ever
        removes one, so after a hundred seasons every house has someone to
        quarrel with at all times. Lapsing is not settlement — the marker goes to
        resolved, not to friendship — it is the quarrel ceasing to be worth the
        trouble.
        """
        window = self.rules.friction["grievance_lapse"]["seasons"]
        for row in self.conn.execute(
            "SELECT id, house_a, house_b, event_id FROM relations WHERE marker = ?",
            (GRIEVANCE,),
        ).fetchall():
            made = self._relation_season(row["house_a"], row["house_b"])
            if made is not None and (season - made) >= window:
                self.conn.execute(
                    "UPDATE relations SET marker = ?, event_text = ? WHERE id = ?",
                    (RESOLVED, "lapsed: no longer pressed", row["id"]),
                )

    def _run_friction(self, season, rng):
        """Move every border, then let the hottest ones break (rules 0.6)."""
        self._lapse_grievances(season)
        spec = self.rules.friction["flashpoint"]
        profiles = {}

        for house_a, house_b in self.bordering_pairs():
            for house in (house_a, house_b):
                if house not in profiles:
                    profiles[house] = self.house_row(house)
            row_a, row_b = profiles[house_a], profiles[house_b]
            marker = self.relation_marker(house_a, house_b)

            value = self.friction_between(house_a, house_b)
            value = self._set_friction(
                house_a, house_b, value + self._friction_delta(row_a, row_b, marker)
            )

            if value < spec["threshold"]:
                continue
            # A border at the threshold is ready to break, not obliged to.
            if rng.die(6, purpose=f"friction.flashpoint.{house_a}|{house_b}") >= spec["succeeds_on"]:
                if marker not in (KIN, COMPACT):
                    grievance = self._grievance_template(row_a, row_b, rng)
                    band = self.band_for(self.personal_year(house_a))
                    event_id = self.record(
                        "relational",
                        f"{row_a['peerage']} and {row_b['peerage']} fall out",
                        [house_a, house_b],
                        season,
                        band=band,
                        line=f"Season {season} · {row_a['peerage']} and {row_b['peerage']} "
                             f"fall out over {grievance}.",
                        delta={"marker": GRIEVANCE, "cause": "friction", "grievance": grievance},
                    )
                    self.set_relation(house_a, house_b, GRIEVANCE, event_id, grievance)
            self._set_friction(house_a, house_b, spec["resets_to"])

    # ---------------------------------------------------------- action loop --

    def legal_actions(self, house):
        """The actions this house could take, with §7's preconditions applied."""
        row = self.house_row(house)
        holder = self.holder(house)
        holdings = self.holding_count(house)
        legal = {"Invest", "Consolidate (rest)"}

        if row["capital"] >= 40 and not row["enclosed"] and self.has_expansion_target(house):
            legal.add("Expand")
        if row["capital"] >= 20:
            legal.add("Cultivate influence")
        if holder is not None and holder["age"] >= 45:
            existing = self.heirs(house)
            second = self.rules.succession["heirs"]
            if not existing:
                legal.add("Name heir")
            elif (
                len(existing) == 1
                and existing[0]["age"] >= second["second_heir_min_age"]
                and holdings >= second["second_heir_min_holdings"]
            ):
                # §9: the second heir is what makes a partition possible later.
                legal.add("Name heir")
        if row["capital"] >= 60:
            legal.add("Endow")
        if (
            row["influence"] >= 60
            and holdings >= 3
            and self.rank_index.get(row["rank"], 0) < self.rank_index["Marquis"]
        ):
            legal.add("Petition elevation")

        # -- PART B: everything that needs another house --
        if self.houses_within_reach(house):
            legal.add("Correspond")

        friendly = self.houses_related_by(house, {FRIENDLY, COMPACT})
        if friendly and row["tag"] in ("Progressive", "Mixed", "Outside", "Conservative"):
            # §7: a compact needs a + relation and a tag that can share one.
            if any(
                self.house_row(other)["tag"] == row["tag"]
                or "Mixed" in (row["tag"], self.house_row(other)["tag"])
                for other in friendly
            ):
                legal.add("Propose compact")
        if friendly and self._unmarried_heir(house):
            if any(self._unmarried_heir(other) for other in friendly):
                legal.add("Marriage alliance")

        aggrieved = self.houses_related_by(house, {GRIEVANCE})
        if aggrieved:
            legal.add("Reconcile")
            if any(
                self._adjacent_holding_of(house, other)
                and not self._dispute_blocked(house, other, self.season_no)
                for other in aggrieved
            ):
                legal.add("Dispute")
            if any(self._adjacent_holding_of(house, other) for other in aggrieved):
                legal.add("Cede / swap")

        if self.houses_related_by(house, {HOSTILE}) and any(
            self._adjacent_holding_of(house, other)
            for other in self.houses_related_by(house, {HOSTILE})
        ):
            legal.add("Challenge (11b)")

        if row["capital"] >= 70 and self._purchase_targets(house):
            legal.add("Purchase riding")
        if self._absorb_targets(house):
            legal.add("Absorb")

        return legal & IMPLEMENTED_ACTIONS

    def _purchase_targets(self, house):
        """A neighbour short of money or order, holding a riding next to ours (§7)."""
        out = []
        for other in self.neighbouring_houses(house):
            row = self.house_row(other)
            if (row["capital"] < 30 or row["cohesion"] < 35) and self._adjacent_holding_of(house, other):
                out.append(other)
        return out

    def _absorb_targets(self, house):
        """A failing neighbour we are already bound to (§7). The binding is what
        makes absorption different from conquest."""
        bound = set(self.houses_related_by(house, {COMPACT, KIN}))
        return [
            other
            for other in self.neighbouring_houses(house)
            if other in bound and self.house_row(other)["cohesion"] < 15
        ]

    def action_weights(self, house, legal):
        """§7's base weights with the modifiers the design states, plus the
        objective bonuses from rules/objectives.csv and §7b's enclosure doubling."""
        row = self.house_row(house)
        holder = self.holder(house)
        held = self.held_objectives(house)

        bonus_for = defaultdict(float)
        for objective in held:
            spec = self.objectives.get(objective)
            if spec is None:
                continue
            for action in spec.action_weight_bonus:
                bonus_for[action] += 2.0

        weights = {}
        for name in sorted(legal):
            action = self.actions[name]
            try:
                weight = float(action.base_weight)
            except ValueError:
                continue  # 'forced' actions are never drawn from the pool

            if name == "Expand":
                weight += row["ambition"]
                if row["cohesion"] < 40:
                    weight -= 2
            elif name == "Invest" and row["capital"] < 40:
                weight += 2
            elif name == "Consolidate (rest)" and row["cohesion"] < 40:
                weight += 3
            elif name == "Name heir" and holder is not None and holder["age"] > 60:
                weight += (holder["age"] - 60) // 5
            elif name == "Dispute":
                weight += row["ambition"] / 2
                if row["cohesion"] < 50:
                    weight -= 3
            elif name == "Reconcile" and row["cohesion"] < 40:
                weight += 2
            elif name == "Correspond":
                same_tag = [
                    other for other in self.houses_within_reach(house)
                    if self.house_row(other)["tag"] == row["tag"]
                ]
                if same_tag:
                    weight += 2
                if self.houses_related_by(house, {GRIEVANCE}):
                    weight -= 2

            weight += bonus_for.get(name, 0.0)
            if row["enclosed"] and name in ENCLOSURE_DOUBLED:
                weight *= 2
            weights[name] = max(0.0, weight)
        return weights

    def take_action(self, house, season, rng):
        legal = self.legal_actions(house)
        weights = self.action_weights(house, legal)
        name = rng.weighted(weights, purpose=f"action.{house}")
        if name is None:
            return None
        return self.resolve_action(house, name, season, rng)

    def resolve_action(self, house, name, season, rng):
        """Roll 2d6 + modifiers against the action's target and apply the outcome."""
        action = self.actions[name]
        row = self.house_row(house)
        band = self.band_for(self.personal_year(house))

        if action.target == "auto":
            success = True
            roll = None
        else:
            roll = rng.two_d6(purpose=f"resolve.{name}.{house}")
            modifier = int(action.enclosure_bonus.lstrip("+") or 0) if row["enclosed"] and action.enclosure_bonus else 0
            success = roll + modifier >= action.target

        handler = getattr(self, f"_do_{_slug(name)}")
        return handler(house, season, rng, success, band, roll)

    # -- the PART A actions --

    def _do_expand(self, house, season, rng, success, band, roll):
        row = self.house_row(house)
        if not success:
            self.set_stats(house, capital=-5)
            return {"action": "Expand", "success": False}

        targets = self.expansion_targets(house)
        if not targets:
            return {"action": "Expand", "success": False, "note": "no target"}
        fed_id = rng.choice(targets, purpose=f"expand.target.{house}")
        name = self._riding_name(fed_id)

        # Contested expansion (rules 0.6): if another house already reached for
        # this riding this season, the two roll off. The loser walks away with a
        # grievance, which is how a land rush turns into a quarrel.
        rival = self._expansion_claims.get(fed_id)
        if rival is not None and rival["house"] != house:
            mine = rng.two_d6(purpose=f"contest.{house}.{fed_id}")
            if mine <= rival["roll"]:
                self._grievance_from_contest(house, rival["house"], name, season, band)
                self.set_stats(house, capital=-5)
                return {"action": "Expand", "success": False, "note": "lost the contest",
                        "riding": name, "to": rival["house"]}
            # We outbid the house that took it: it loses the riding again.
            self._grievance_from_contest(rival["house"], house, name, season, band)
            self.conn.execute(
                "UPDATE holdings SET released_event_id = acquired_event_id"
                " WHERE house = ? AND fed_id = ? AND released_event_id IS NULL",
                (rival["house"], fed_id),
            )
            self._renumber(rival["house"])
            self._expansion_claims[fed_id] = {"house": house, "roll": mine}
        else:
            self._expansion_claims[fed_id] = {
                "house": house,
                "roll": rng.two_d6(purpose=f"contest.{house}.{fed_id}"),
            }

        event_id = self.record(
            "expansion",
            f"{row['peerage']} takes {name}",
            [house],
            season,
            band=band,
            line=f"Season {season} · {row['peerage']} takes {name}.",
            delta={"riding": name, "roll": roll},
        )
        self.conn.execute(
            "INSERT INTO holdings (house, fed_id, seat_order, hex, acquired_event_id)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                house,
                fed_id,
                mechanics._next_seat_order(self.conn, house),
                mechanics._expansion_hex(self.conn, house),
                event_id,
            ),
        )
        self.set_stats(house, capital=-15)
        return {"action": "Expand", "success": True, "riding": name}

    def _grievance_from_contest(self, loser, winner, riding, season, band):
        """The house that lost a contested riding carries the grievance."""
        if self.relation_marker(loser, winner) in (KIN, COMPACT):
            return
        event_id = self.record(
            "relational",
            f"{self.house_row(loser)['peerage']} loses {riding} to"
            f" {self.house_row(winner)['peerage']}",
            [loser, winner],
            season,
            band=band,
            delta={"marker": GRIEVANCE, "cause": "contested expansion", "riding": riding},
        )
        self.set_relation(loser, winner, GRIEVANCE, event_id, f"contested claim to {riding}")

    def _do_invest(self, house, season, rng, success, band, roll):
        self.set_stats(house, capital=8)
        return {"action": "Invest", "success": True}

    def _do_cultivate_influence(self, house, season, rng, success, band, roll):
        if success:
            self.set_stats(house, influence=6, capital=-5)
        else:
            self.set_stats(house, capital=-5)
        return {"action": "Cultivate influence", "success": success}

    def _do_consolidate_rest(self, house, season, rng, success, band, roll):
        self.set_stats(house, cohesion=8)
        return {"action": "Consolidate (rest)", "success": True}

    def _do_name_heir(self, house, season, rng, success, band, roll):
        row = self.house_row(house)
        holder = self.holder(house)
        if holder is None:
            return {"action": "Name heir", "success": False}
        existing = self.heirs(house)
        role = "heir2" if existing else "heir"
        heir_age = max(0, holder["age"] - (25 + rng.randint(1, 15, "heir.age_gap")))
        generator = NameGenerator(self.rules, rng)
        given, surname, gender = generator.draw_person(
            row["community"], surname=house.split(" ")[0]
        )
        self.conn.execute(
            "INSERT INTO persons (house, name, gender, age, role, alive, born_season)"
            " VALUES (?, ?, ?, ?, ?, 1, ?)",
            (house, f"{given} {surname}", gender, heir_age, role, season),
        )
        if role == "heir2":
            # §9: naming a second heir steadies the house now and enables partition later.
            self.set_stats(house, cohesion=3)
        self.record(
            "other",
            f"{row['peerage']} names an heir",
            [house],
            season,
            band=band,
            line=f"Season {season} · {row['peerage']} names {given} {surname}"
                 f"{' second heir' if role == 'heir2' else ' heir'}.",
            delta={"heir_age": heir_age, "role": role},
        )
        return {"action": "Name heir", "success": True, "role": role}

    def _do_endow(self, house, season, rng, success, band, roll):
        row = self.house_row(house)
        self.set_stats(house, influence=10, cohesion=5, capital=-25)
        self.record(
            "other",
            f"{row['peerage']} endows an institution",
            [house],
            season,
            band=band,
            line=f"Season {season} · {row['peerage']} endows an institution.",
        )
        self._satisfy_objective(house, "Endow an institution", season)
        return {"action": "Endow", "success": True}

    def _do_petition_elevation(self, house, season, rng, success, band, roll):
        row = self.house_row(house)
        if not success:
            self.set_stats(house, influence=-5)
            return {"action": "Petition elevation", "success": False}

        ladder = [r for r, _ in mechanics.RANK_LADDER]
        current = self.rank_index.get(row["rank"], 0)
        new_rank = ladder[min(current + 1, len(ladder) - 1)]
        try:
            peerage = mechanics.elevate(self.conn, house, new_rank, None)
        except mechanics.RuleError:
            return {"action": "Petition elevation", "success": False}

        self.set_stats(house, influence=-10)
        self.record(
            "elevation",
            f"{peerage} elevated",
            [house],
            season,
            band=band,
            line=f"Season {season} · {row['peerage']} is raised to {new_rank}.",
            delta={"from": row["rank"], "to": new_rank},
        )
        self._satisfy_objective(house, "Seek elevation", season)
        return {"action": "Petition elevation", "success": True, "rank": new_rank}


    # -- the PART B actions --

    def _pick(self, rng, options, purpose):
        if not options:
            return None
        return rng.choice(sorted(options), purpose=purpose)

    def _do_correspond(self, house, season, rng, success, band, roll):
        """Letters between houses: the slow start of every relation (§7)."""
        row = self.house_row(house)
        reachable = self.houses_within_reach(house)
        if not reachable:
            return {"action": "Correspond", "success": False, "note": "no one in reach"}

        # Prefer a house we already know: correspondence deepens before it spreads.
        known = [o for o in reachable if self.relation_marker(house, o) == ACQUAINTED]
        other = self._pick(rng, known or reachable, f"correspond.target.{house}")
        if other is None:
            return {"action": "Correspond", "success": False}

        # A natural 2 is the letter that gives offence (rules 0.6). §7 gave
        # Correspond no failure effect at all, which made it a free action.
        fumble = self.rules.friction["correspond_fumble"]
        if roll == fumble["natural"] and self.relation_marker(house, other) not in (KIN, COMPACT):
            other_row = self.house_row(other)
            event_id = self.record(
                "relational",
                f"{row['peerage']} gives offence to {other_row['peerage']}",
                [house, other],
                season,
                band=band,
                line=f"Season {season} · a letter from {row['peerage']} gives offence to "
                     f"{other_row['peerage']}.",
                delta={"marker": GRIEVANCE, "cause": "correspondence"},
            )
            self.set_relation(house, other, GRIEVANCE, event_id, "a letter that gave offence")
            return {"action": "Correspond", "success": False, "with": other, "fumble": True}

        if not success:
            return {"action": "Correspond", "success": False}

        current = self.relation_marker(house, other)
        marker = FRIENDLY if current == ACQUAINTED else (current or ACQUAINTED)
        if current in (COMPACT, KIN, GRIEVANCE, HOSTILE, CHALLENGED):
            marker = current  # correspondence does not undo a compact or a grievance

        other_row = self.house_row(other)
        event_id = self.record(
            "relational",
            f"{row['peerage']} corresponds with {other_row['peerage']}",
            [house, other],
            season,
            band=band,
            line=f"Season {season} · {row['peerage']} opens a correspondence with "
                 f"{other_row['peerage']}.",
            delta={"marker": marker},
        )
        self.set_relation(house, other, marker, event_id, "correspondence")
        return {"action": "Correspond", "success": True, "with": other, "marker": marker}

    def _do_propose_compact(self, house, season, rng, success, band, roll):
        row = self.house_row(house)
        candidates = [
            other for other in self.houses_related_by(house, {FRIENDLY})
            if self.house_row(other)["tag"] == row["tag"]
            or "Mixed" in (row["tag"], self.house_row(other)["tag"])
        ]
        other = self._pick(rng, candidates, f"compact.target.{house}")
        if other is None or not success:
            return {"action": "Propose compact", "success": False}

        other_row = self.house_row(other)
        event_id = self.record(
            "relational",
            f"{row['peerage']} and {other_row['peerage']} form a compact",
            [house, other],
            season,
            band=band,
            line=f"Season {season} · {row['peerage']} and {other_row['peerage']} "
                 "enter into a compact.",
            delta={"marker": COMPACT},
        )
        self.set_relation(house, other, COMPACT, event_id, "compact")
        self.set_stats(house, cohesion=5)
        self.set_stats(other, cohesion=5)
        self._satisfy_objective(house, "Form a compact", season)
        self._satisfy_objective(other, "Form a compact", season)
        self._satisfy_objective(house, "Siege", season)
        return {"action": "Propose compact", "success": True, "with": other}

    def _do_reconcile(self, house, season, rng, success, band, roll):
        row = self.house_row(house)
        other = self._pick(
            rng, self.houses_related_by(house, {GRIEVANCE}), f"reconcile.target.{house}"
        )
        if other is None or not success:
            return {"action": "Reconcile", "success": False}

        other_row = self.house_row(other)
        event_id = self.record(
            "relational",
            f"{row['peerage']} reconciles with {other_row['peerage']}",
            [house, other],
            season,
            band=band,
            line=f"Season {season} · {row['peerage']} makes peace with {other_row['peerage']}.",
            delta={"marker": RESOLVED},
        )
        self.set_relation(house, other, RESOLVED, event_id, "reconciliation")
        self._satisfy_objective(house, "Answer a grievance", season)
        return {"action": "Reconcile", "success": True, "with": other}

    def _do_dispute(self, house, season, rng, success, band, roll):
        row = self.house_row(house)
        candidates = [
            other for other in self.houses_related_by(house, {GRIEVANCE})
            if self._adjacent_holding_of(house, other)
            and not self._dispute_blocked(house, other, season)
        ]
        other = self._pick(rng, candidates, f"dispute.target.{house}")
        if other is None:
            return {"action": "Dispute", "success": False}

        other_row = self.house_row(other)
        if not success:
            self.set_stats(house, cohesion=-10)
            self.record(
                "relational",
                f"{row['peerage']} loses a dispute with {other_row['peerage']}",
                [house, other],
                season,
                band=band,
                line=f"Season {season} · {row['peerage']} presses a claim against "
                     f"{other_row['peerage']} and is rebuffed.",
                delta={"outcome": "lost"},
            )
            return {"action": "Dispute", "success": False, "with": other}

        self.set_stats(other, cohesion=-10)
        # §7: the grievance either resolves or hardens into open hostility, which
        # is what makes a Challenge legal later.
        hardens = self.rules.friction["dispute_outcome"]["hardens_probability"]
        marker = HOSTILE if rng.chance(hardens, purpose=f"dispute.hardens.{house}") else RESOLVED
        event_id = self.record(
            "relational",
            f"{row['peerage']} wins a dispute with {other_row['peerage']}",
            [house, other],
            season,
            band=band,
            line=f"Season {season} · {row['peerage']} carries a dispute against "
                 f"{other_row['peerage']}.",
            delta={"outcome": "won", "marker": marker},
        )
        self.set_relation(house, other, marker, event_id, "dispute won")
        # A dispute is a direct shared event, so the clocks meet (hard rule 5).
        self._sync(house, other, event_id, season)
        self._satisfy_objective(house, "Answer a grievance", season)
        return {"action": "Dispute", "success": True, "with": other, "marker": marker}

    def _sync(self, house_a, house_b, event_id, season):
        """Two houses that met set their clocks to the later of the two (§3)."""
        year = max(self.personal_year(house_a), self.personal_year(house_b))
        for house in (house_a, house_b):
            self.conn.execute(
                "UPDATE clocks SET personal_year = ?, basis = ? WHERE house = ?",
                (year, f"synced at season {season}, event {event_id}", house),
            )
        self.conn.execute(
            "UPDATE event_houses SET personal_year = ? WHERE event_id = ?", (year, event_id)
        )

    def _do_challenge_11b(self, house, season, rng, success, band, roll):
        """The v1 incursion table, kept: tag against the climate, plus rank."""
        row = self.house_row(house)
        candidates = [
            other for other in self.houses_related_by(house, {HOSTILE})
            if self._adjacent_holding_of(house, other)
        ]
        other = self._pick(rng, candidates, f"challenge.target.{house}")
        if other is None:
            return {"action": "Challenge (11b)", "success": False}

        other_row = self.house_row(other)
        try:
            climate = mechanics.current_climate(self.conn, band)
        except mechanics.RuleError:
            climate = 0
        modifier = {"Progressive": 3, "Conservative": -3, "Outside": 6}.get(row["tag"], 0)
        modifier = modifier if climate >= 0 else -modifier
        modifier += max(
            0, self.rank_index.get(row["rank"], 0) - self.rank_index.get(other_row["rank"], 0)
        )
        if row["enclosed"]:
            modifier += 2  # §7b enclosure bonus, rules 0.3

        total = (roll if roll is not None else rng.two_d6(f"challenge.roll.{house}")) + modifier
        if total < self.actions["Challenge (11b)"].target:
            self.set_stats(house, ambition=-2, influence=-5)
            event_id = self.record(
                "challenge",
                f"{row['peerage']} fails against {other_row['peerage']}",
                [house, other],
                season,
                band=band,
                line=f"Season {season} · {row['peerage']} challenges "
                     f"{other_row['peerage']} and fails.",
                delta={"outcome": "failed", "total": total},
            )
            # The attempt spends the hostility (rules 0.6): the quarrel stands,
            # but the moment for arms has passed.
            self.set_relation(
                house, other, self.rules.friction["challenge_outcome"]["failure_marker"],
                event_id, "a challenge that failed",
            )
            return {"action": "Challenge (11b)", "success": False, "with": other}

        fed_id = self._adjacent_holding_of(house, other)
        name = self._riding_name(fed_id)
        event_id = self.record(
            "challenge",
            f"{row['peerage']} takes {name} from {other_row['peerage']}",
            [house, other],
            season,
            band=band,
            line=f"Season {season} · {row['peerage']} takes {name} from "
                 f"{other_row['peerage']} by challenge.",
            delta={"outcome": "won", "riding": name, "total": total, "marker": CHALLENGED},
        )
        self.conn.execute(
            "UPDATE holdings SET released_event_id = ? WHERE house = ? AND fed_id = ?"
            " AND released_event_id IS NULL",
            (event_id, other, fed_id),
        )
        self.conn.execute(
            "INSERT INTO holdings (house, fed_id, seat_order, hex, acquired_event_id)"
            " VALUES (?, ?, ?, ?, ?)",
            (house, fed_id, mechanics._next_seat_order(self.conn, house),
             mechanics._expansion_hex(self.conn, house), event_id),
        )
        self.set_relation(house, other, CHALLENGED, event_id, f"challenge over {name}")
        self._sync(house, other, event_id, season)
        return {"action": "Challenge (11b)", "success": True, "with": other, "riding": name}

    def _do_purchase_riding(self, house, season, rng, success, band, roll):
        row = self.house_row(house)
        other = self._pick(rng, self._purchase_targets(house), f"purchase.target.{house}")
        if other is None:
            return {"action": "Purchase riding", "success": False}
        if not success:
            self.set_stats(house, capital=-5)
            return {"action": "Purchase riding", "success": False, "with": other}

        fed_id = self._adjacent_holding_of(house, other)
        seat = self.conn.execute(
            "SELECT seat_order FROM holdings WHERE house = ? AND fed_id = ?"
            " AND released_event_id IS NULL",
            (other, fed_id),
        ).fetchone()
        if fed_id is None or seat is None or seat["seat_order"] == 1:
            return {"action": "Purchase riding", "success": False, "note": "only the seat on offer"}

        other_row = self.house_row(other)
        name = self._riding_name(fed_id)
        event_id = self.record(
            "transfer",
            f"{row['peerage']} buys {name} from {other_row['peerage']}",
            [house, other],
            season,
            band=band,
            line=f"Season {season} · {row['peerage']} buys {name} from {other_row['peerage']}.",
            delta={"riding": name, "price": 40},
        )
        self.conn.execute(
            "UPDATE holdings SET released_event_id = ? WHERE house = ? AND fed_id = ?"
            " AND released_event_id IS NULL",
            (event_id, other, fed_id),
        )
        self.conn.execute(
            "INSERT INTO holdings (house, fed_id, seat_order, hex, acquired_event_id)"
            " VALUES (?, ?, ?, ?, ?)",
            (house, fed_id, mechanics._next_seat_order(self.conn, house),
             mechanics._expansion_hex(self.conn, house), event_id),
        )
        self.set_stats(house, capital=-40)
        self.set_stats(other, capital=30)
        self._sync(house, other, event_id, season)
        return {"action": "Purchase riding", "success": True, "with": other, "riding": name}

    def _do_marriage_alliance(self, house, season, rng, success, band, roll):
        row = self.house_row(house)
        candidates = [
            other for other in self.houses_related_by(house, {FRIENDLY, COMPACT})
            if self._unmarried_heir(other)
        ]
        other = self._pick(rng, candidates, f"marriage.target.{house}")
        if other is None or not self._unmarried_heir(house) or not success:
            return {"action": "Marriage alliance", "success": False}

        other_row = self.house_row(other)
        mine = self._unmarried_heir(house)
        theirs = self._unmarried_heir(other)
        event_id = self.record(
            "relational",
            f"{row['peerage']} and {other_row['peerage']} are joined by marriage",
            [house, other],
            season,
            band=band,
            line=f"Season {season} · {mine['name']} marries {theirs['name']}, "
                 f"binding {row['peerage']} to {other_row['peerage']}.",
            delta={"marker": KIN},
        )
        self.conn.execute(
            "UPDATE persons SET married = 1 WHERE id IN (?, ?)", (mine["id"], theirs["id"])
        )
        self.set_relation(house, other, KIN, event_id, "marriage alliance")
        self.set_stats(house, cohesion=5)
        self.set_stats(other, cohesion=5)
        self._sync(house, other, event_id, season)
        self._satisfy_objective(house, "Form a compact", season)
        self._satisfy_objective(other, "Form a compact", season)
        self._satisfy_objective(house, "Siege", season)
        return {"action": "Marriage alliance", "success": True, "with": other}

    def _do_absorb(self, house, season, rng, success, band, roll):
        row = self.house_row(house)
        other = self._pick(rng, self._absorb_targets(house), f"absorb.target.{house}")
        if other is None:
            return {"action": "Absorb", "success": False}
        if not success:
            event_id = self.record(
                "relational",
                f"{row['peerage']} fails to absorb {self.house_row(other)['peerage']}",
                [house, other],
                season,
                band=band,
                delta={"marker": GRIEVANCE},
            )
            self.set_relation(house, other, GRIEVANCE, event_id, "failed absorption")
            return {"action": "Absorb", "success": False, "with": other}

        self._absorb_into(house, other, season, band, reason="absorption")
        return {"action": "Absorb", "success": True, "with": other}

    def _absorb_into(self, house, other, season, band, reason):
        """The absorbed house's holdings pass as a cadet block and the house is
        removed from play, keeping its history (§7, §9)."""
        row = self.house_row(house)
        other_row = self.house_row(other)
        event_id = self.record(
            "transfer",
            f"{row['peerage']} absorbs {other_row['peerage']}",
            [house, other],
            season,
            band=band,
            line=f"Season {season} · {row['peerage']} absorbs {other_row['peerage']}.",
            delta={"nature": "absorption", "reason": reason},
        )
        holdings = self.conn.execute(
            "SELECT id, fed_id FROM holdings WHERE house = ? AND released_event_id IS NULL"
            " ORDER BY seat_order",
            (other,),
        ).fetchall()
        for holding in holdings:
            self.conn.execute(
                "UPDATE holdings SET released_event_id = ? WHERE id = ?", (event_id, holding["id"])
            )
            self.conn.execute(
                "INSERT INTO holdings (house, fed_id, seat_order, hex, acquired_event_id)"
                " VALUES (?, ?, ?, ?, ?)",
                (house, holding["fed_id"], mechanics._next_seat_order(self.conn, house),
                 mechanics._expansion_hex(self.conn, house), event_id),
            )
        self.set_stats(house, cohesion=-10)
        self.conn.execute("UPDATE houses SET status = 'removed' WHERE house = ?", (other,))
        self.conn.execute(
            "UPDATE house_stats SET removed_season = ? WHERE house = ?", (season, other)
        )
        self.conn.execute(
            "UPDATE persons SET alive = 0, died_season = ? WHERE house = ? AND alive = 1",
            (season, other),
        )
        return event_id

    def _do_cede_swap(self, house, season, rng, success, band, roll):
        row = self.house_row(house)
        candidates = [
            other for other in self.houses_related_by(house, {GRIEVANCE})
            if self._adjacent_holding_of(house, other)
        ]
        other = self._pick(rng, candidates, f"cede.target.{house}")
        if other is None or not success:
            return {"action": "Cede / swap", "success": False}

        other_row = self.house_row(other)
        ceded = self._lose_riding(house, season, reason="cession", to_house=other)
        event_id = self.record(
            "relational",
            f"{row['peerage']} settles with {other_row['peerage']}",
            [house, other],
            season,
            band=band,
            line=f"Season {season} · {row['peerage']} settles its grievance with "
                 f"{other_row['peerage']} by cession.",
            delta={"marker": RESOLVED, "ceded": ceded},
        )
        self.set_relation(house, other, RESOLVED, event_id, "cession")
        self._sync(house, other, event_id, season)
        self._satisfy_objective(house, "Answer a grievance", season)
        return {"action": "Cede / swap", "success": True, "with": other}

    # ------------------------------------------------------------ objectives --

    def _satisfy_objective(self, house, objective, season):
        self.conn.execute(
            "UPDATE objectives SET satisfied_season = ? WHERE house = ? AND objective = ?"
            " AND satisfied_season IS NULL",
            (season, house, objective),
        )

    def _contiguous_holdings(self, house):
        """The size of the largest land-connected block the house holds."""
        fed_ids = [
            row["fed_id"]
            for row in self.conn.execute(
                "SELECT fed_id FROM holdings WHERE house = ? AND released_event_id IS NULL",
                (house,),
            )
        ]
        if len(fed_ids) < 2:
            return len(fed_ids)
        held = set(fed_ids)
        edges = defaultdict(set)
        placeholders = ",".join("?" for _ in fed_ids)
        for row in self.conn.execute(
            f"SELECT fed_id_a, fed_id_b FROM adjacency WHERE adjacency_type = 'land'"
            f" AND fed_id_a IN ({placeholders}) AND fed_id_b IN ({placeholders})",
            fed_ids + fed_ids,
        ):
            edges[row["fed_id_a"]].add(row["fed_id_b"])
            edges[row["fed_id_b"]].add(row["fed_id_a"])

        best, seen = 0, set()
        for start in fed_ids:
            if start in seen:
                continue
            stack, size = [start], 0
            while stack:
                node = stack.pop()
                if node in seen:
                    continue
                seen.add(node)
                size += 1
                stack.extend(n for n in edges[node] & held if n not in seen)
            best = max(best, size)
        return best

    def _check_objectives(self, house, season, rng):
        """Mark satisfied objectives and draw replacements, at most once a season."""
        row = self.house_row(house)
        for objective in self.held_objectives(house):
            satisfied = False
            if objective == "Consolidate region":
                satisfied = self._contiguous_holdings(house) >= 4
            elif objective == "Secure succession":
                heirs = self.heirs(house)
                satisfied = bool(heirs) and heirs[0]["age"] >= 25
            elif objective == "Defend the seat":
                since = self._seasons_since_loss(house)
                satisfied = since is not None and since >= DEFEND_THE_SEAT_SEASONS
            elif objective == "Siege":
                since = self._seasons_since_loss(house)
                satisfied = since is not None and since >= SIEGE_SEASONS
            if satisfied:
                self._satisfy_objective(house, objective, season)

        held = self.held_objectives(house)
        if len(held) < OBJECTIVES_AT_FOUNDING:
            weights = {
                o.objective: 1.0 + 2.0 * self._objective_favoured(o.objective, row, house)
                for o in self.rules.objectives
                if o.objective not in held
            }
            chosen = rng.weighted(weights, purpose=f"objective.replace.{house}")
            if chosen is not None and len(held) < MAX_OBJECTIVES:
                self.conn.execute(
                    "INSERT INTO objectives (house, objective, acquired_season) VALUES (?, ?, ?)",
                    (house, chosen, season),
                )

    def _seasons_since_loss(self, house):
        """Seasons since this house last lost a riding, or since it was founded
        if it never has. Read from the event log rather than kept in memory, so a
        replay in a fresh process sees the same history."""
        row = self.conn.execute(
            "SELECT e.mechanical_delta FROM events e"
            " JOIN event_houses eh ON eh.event_id = e.id AND eh.house = ?"
            " WHERE e.kind = 'transfer' ORDER BY e.id DESC LIMIT 1",
            (house,),
        ).fetchone()
        stats = self.house_row(house)
        if row is None:
            founded = stats["founded_season"]
            return None if founded is None else self.season_no - founded
        try:
            last = json.loads(row["mechanical_delta"])["season"]
        except (TypeError, ValueError, KeyError):
            return None
        return self.season_no - last

    # ------------------------------------------------------------- enclosure --

    def _recompute_enclosure(self, season):
        """§7b: a house is enclosed when no unclaimed riding is land-adjacent to
        any of its holdings. Ambition drifts with the pressure of it."""
        unenclosed = self.unenclosed_houses()
        for row in self.active_houses():
            house = row["house"]
            enclosed = 0 if house in unenclosed else 1
            was = row["enclosed"]
            since = row["enclosed_since"]

            if enclosed and not was:
                since = season
            elif not enclosed:
                since = None

            self.conn.execute(
                "UPDATE house_stats SET enclosed = ?, enclosed_since = ? WHERE house = ?",
                (enclosed, since, house),
            )

            if enclosed and since is not None and (season - since) > 0 and (season - since) % 10 == 0:
                drift = -1 if row["tag"] == "Progressive" else 1
                self.set_stats(house, ambition=drift)

            # §7b: a house shut in on every side and coming apart draws Siege —
            # survive, or find a protector. Satisfied by a compact or a marriage.
            if enclosed and row["cohesion"] < 40:
                held = self.held_objectives(house)
                if "Siege" not in held and len(held) < MAX_OBJECTIVES:
                    self.conn.execute(
                        "INSERT INTO objectives (house, objective, acquired_season)"
                        " VALUES (?, 'Siege', ?)",
                        (house, season),
                    )

    # ---------------------------------------------------------------- debt --

    def _debt_check(self, house, season, rng):
        """Capital at zero for three consecutive seasons forces a sale (§7c).

        Capital is clamped at 0 rather than allowed negative, so 'below 0' is
        read as 'at the floor': a house with nothing left to spend is in the same
        position the rule describes.
        """
        row = self.house_row(house)
        if row["capital"] > 0:
            return
        recent = self.conn.execute(
            "SELECT COUNT(*) AS n FROM events e JOIN event_houses eh ON eh.event_id = e.id"
            " AND eh.house = ? WHERE e.kind = 'transfer' AND e.title LIKE '%debt%'",
            (house,),
        ).fetchone()["n"]
        if recent:
            return
        if self.holding_count(house) > 1:
            self._sell_riding(house, season, reason="debt")

    # ------------------------------------------------------------ the season --

    def rng_for(self, season_no):
        return LoggingRandom(random.Random(season_seed(self.world_seed, season_no)), self.log)

    def initialise(self, world_seed, seat=None):
        """Season 1: exactly one house is founded (§10, and the director's first
        decision). Everything after it arrives by the founding roll."""
        self.world_seed = world_seed
        self.log = []
        self.chronicle = []
        rng = self.rng_for(1)

        house = self.found_house(1, seat=seat, rng=rng)
        if house is None:
            raise SimError("season 1 founded no house: the map has no unclaimed riding")

        record = self._write_season(1, [], house)
        record["kind"] = "initial"
        record["seat"] = seat
        self._rewrite_season_file(1, record)
        return record

    def _write_season_file(self, season, record):
        """Write one season log, and return the repo-relative path recorded in
        the seasons row. A world with no seasons_dir writes nothing and records
        NULL — the database still holds the season, only the log is skipped."""
        if self.seasons_dir is None:
            return None
        self.seasons_dir.mkdir(parents=True, exist_ok=True)
        path = self.seasons_dir / f"{season:04d}.json"
        path.write_text(
            json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        try:
            return str(path.relative_to(scenario.REPO_ROOT))
        except ValueError:
            return str(path)

    def _rewrite_season_file(self, season, record):
        """Re-write a season log after adding fields the writer did not know."""
        self._write_season_file(season, record)

    def run_season(self, season_no=None):
        """Play one season, in §6's order. Returns the season's log record."""
        season = season_no if season_no is not None else self.season_no + 1
        self.log = []
        self.chronicle = []
        rng = self.rng_for(season)

        # 1. Clocks and ages.
        self._age_everyone(season)

        # Borders warm or cool before anyone acts, so a grievance struck this
        # season is available to the houses that act after it (rules 0.6).
        self._turn_cache = {}
        self._run_friction(season, rng)

        outcomes = []
        self._expansion_claims = {}
        for row in self.active_houses():
            house = row["house"]
            self._turn_cache = {}
            if self.house_row(house)["removed_season"] is not None:
                continue

            # 2. Era events, which may demand an extra mortality roll.
            fired = self._era_event(house, season, rng)
            extra_mortality = bool(fired and fired["extra_mortality"])

            # 3. Mortality and succession.
            if self._mortality(house, season, rng, extra_roll=extra_mortality):
                continue

            # 4-5. Action selection and resolution.
            outcome = self.take_action(house, season, rng)
            if outcome:
                outcomes.append(outcome)
                self.conn.execute(
                    "INSERT INTO house_actions (season_no, house, action, success, detail)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        season,
                        house,
                        outcome.get("action", "—"),
                        1 if outcome.get("success") else 0,
                        outcome.get("riding") or outcome.get("with") or outcome.get("note"),
                    ),
                )

            # 6. Objectives, then the §7c debt check.
            self._check_objectives(house, season, rng)
            self._debt_check(house, season, rng)

        # 7. Founding roll.
        founded = self._founding_roll(season, rng)

        # 8. Enclosure recompute.
        self._recompute_enclosure(season)

        # 9-10. The season record.
        return self._write_season(season, outcomes, founded)

    def _founding_roll(self, season, rng):
        """§10: high on an empty map, falling smoothly to zero as land runs out.

        The coefficient and exponent come from rules/founding.json, not from
        here — tuning the founding rate is a rules change with a CHANGELOG entry,
        never a code change (§11).
        """
        spec = self.rules.founding["p_found"]
        room = self.unclaimed_land_adjacent_count()
        p_found = spec["coefficient"] * (room / TOTAL_RIDINGS) ** spec["exponent"]
        rng.draw("founding.p_found", {"room": room, "p": round(p_found, 6)})
        if p_found <= 0:
            return None
        if not rng.chance(p_found, purpose="founding.roll"):
            return None
        return self.found_house(season, rng=rng)

    def _snapshot(self, season):
        """Every living house's stats, kept so the site can draw a history the
        live tables cannot: house_stats holds only the present."""
        if season != 1 and season % SNAPSHOT_EVERY != 0:
            return
        self.conn.execute(
            "INSERT OR REPLACE INTO stat_snapshots"
            " (season_no, house, capital, influence, cohesion, ambition, holdings)"
            " SELECT ?, s.house, s.capital, s.influence, s.cohesion, s.ambition,"
            "        (SELECT COUNT(*) FROM holdings h WHERE h.house = s.house"
            "         AND h.released_event_id IS NULL)"
            " FROM house_stats s JOIN houses ho ON ho.house = s.house"
            " WHERE ho.status = 'active'",
            (season,),
        )

    def _write_season(self, season, outcomes, founded):
        self._snapshot(season)
        houses_after = self.conn.execute(
            "SELECT COUNT(*) AS n FROM houses WHERE status = 'active'"
        ).fetchone()["n"]
        ridings_after = self.conn.execute(
            "SELECT COUNT(*) AS n FROM holdings WHERE released_event_id IS NULL"
        ).fetchone()["n"]

        record = {
            "season": season,
            "seed": self.world_seed,
            "rules_version": RULES_VERSION,
            "draws": self.log,
            "actions": outcomes,
            "founded": founded,
            "chronicle": self.chronicle,
            "houses_after": houses_after,
            "ridings_after": ridings_after,
        }

        path = self._write_season_file(season, record)

        self.conn.execute(
            "INSERT OR REPLACE INTO seasons (season_no, seed, json_path, houses_after,"
            " ridings_after, rules_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                season,
                self.world_seed,
                path,
                houses_after,
                ridings_after,
                RULES_VERSION,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        return record

    def run(self, count, stop_on=()):
        """Play `count` seasons, stopping early on any named condition."""
        records = []
        for _ in range(count):
            record = self.run_season()
            records.append(record)
            hit = self._stop_conditions(record) & set(stop_on)
            if hit:
                record["stopped_on"] = sorted(hit)
                break
        return records

    def _stop_conditions(self, record):
        """Which of §12's pause conditions this season met."""
        hit = set()
        season = record["season"]
        rows = self.conn.execute(
            "SELECT e.kind, e.title, e.mechanical_delta FROM events e"
            " WHERE e.source = 'engine' ORDER BY e.id DESC LIMIT 200"
        ).fetchall()
        for row in rows:
            try:
                delta = json.loads(row["mechanical_delta"] or "{}")
            except ValueError:
                continue
            if delta.get("season") != season:
                continue
            if delta.get("nature") == "extinction":
                hit.add("removal")
            if row["kind"] == "challenge":
                hit.add("challenge")
            if delta.get("magnitude") == "Major":
                hit.add("major")
            if delta.get("to") in ("Marquis", "Marchioness"):
                hit.add("marquis")
        return hit

    # ---------------------------------------------------------------- replay --

    @classmethod
    def replay(cls, conn, paths, seasons_dir=None):
        """Re-play an autoplay scenario's seasons into a freshly seeded database.

        The engine is deterministic from (world seed, season number), so the
        seasons are re-run rather than re-applied from their recorded deltas; the
        logs are the audit trail a replay has to reproduce, not the input.
        """
        paths = list(paths)
        if not paths:
            return None
        with open(paths[0], encoding="utf-8") as f:
            first = json.load(f)

        world = cls(conn, world_seed=first["seed"], seasons_dir=seasons_dir)
        for path in paths:
            with open(path, encoding="utf-8") as f:
                record = json.load(f)
            if record.get("kind") == "initial":
                world.initialise(record["seed"], seat=record.get("seat"))
            else:
                world.run_season(record["season"])
        return world


def _slug(action_name):
    """'Consolidate (rest)' -> 'consolidate_rest', the handler-method suffix."""
    cleaned = action_name.lower().replace("(", "").replace(")", "").replace("/", " ")
    return "_".join(cleaned.split())


# Which region a province belongs to, for §10's region weights and for the event
# deck's regional scopes. Newfoundland is grouped with the Maritimes for founding
# (rules/communities.csv has no separate newfoundland community set) while the
# event deck still targets it directly by the `newfoundland` scope.
PROVINCE_REGION = {
    "NL": "maritime",
    "PE": "maritime",
    "NS": "maritime",
    "NB": "maritime",
    "QC": "quebec",
    "ON": "ontario",
    "MB": "prairie",
    "SK": "prairie",
    "AB": "prairie",
    "BC": "bc",
    "YT": "north",
    "NT": "north",
    "NU": "north",
}
