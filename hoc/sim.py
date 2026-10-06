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

import json
from collections import defaultdict
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path

from hoc import palette, places, prng, rules as mechanics, scenario
from hoc.names import NameGenerator, peerage_title
from hoc import rules_data
from hoc.rules_data import load_rules, probability_for_age

__all__ = [
    "PHASES",
    "SimError",
    "LoggingRandom",
    "World",
    "RULES_VERSION",
    "WEIGHT_SCALE",
    "canonical_json",
]

# The version a *new* season is played under, from rules/current.txt. A season
# keeps the version it was played under, and a replay loads that version's
# tables rather than these — so tuning a table never silently reinterprets a
# season that is already in the record (§11, and rules/README.md).
#
# Read at import so callers that only want to know "what is current" keep a
# plain constant to read; a World carries its own `rules_version`, which is the
# one that matters when replaying.
RULES_VERSION = rules_data.current_version()

STAT_RANGE = (0, 100)
AMBITION_RANGE = (0, 10)
TOTAL_RIDINGS = 343

# Rules 0.9 (`atlas_jurisdiction`): every founding and every accession starts a
# personal clock here (hard rule 5), so this is also the year at which a Crown
# grant reads the map. A riding whose opens_year is later is closed to a new
# house, and to any house whose own clock has not yet reached it.
FOUNDING_YEAR = 1867

# Rules 0.9 (`riding_endowments`): the middle quintile. A riding's wealth_tier
# moves founding capital and the cost of taking it by its distance from this.
# A reference set with no riding_stats.csv (ne-2026) reads every riding as this
# tier, so the flag changes nothing there.
NEUTRAL_WEALTH_TIER = 3

# Action weights are carried as integers at this fixed-point scale: a base
# weight of 6 in rules/actions.csv is 600 here, and a "+2" modifier is 200
# (Phase 10-1). Nothing in the weighting is allowed to be a float, because a
# float total and a float target are three roundings deep and cannot be relied
# on to land the same way in Python and in JavaScript — see docs/DETERMINISM.md.
# The scale is 100 so that the one half-point modifier the design states
# (Dispute's +ambition/2) is exact: half of 100 is 50, not 50.000000000000004.
WEIGHT_SCALE = 100

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

# Rules 1.0 `upkeep_phase`: the four standing actions automatic upkeep and the
# automatic letter replace. They leave the action pool under the flag.
UPKEEP_ACTIONS = frozenset({"Invest", "Cultivate influence", "Consolidate (rest)", "Correspond"})

# How a response reads in the chronicle. "Neutral" has no verb of its own.
RESPONSE_VERB = {
    "Lead": "leads",
    "Resist": "resists",
    "Exploit": "exploits",
    "Neutral": "stands aside",
}

# §9's "roll: 20% chance of no successor", as an integer per cent (rules 0.7).
# Stated in rules/succession.json under extinction.triggers; named here because
# it is the one probability the design gives inline rather than in a field.
NO_SUCCESSOR_PCT = 20

MAX_OBJECTIVES = 3
OBJECTIVES_AT_FOUNDING = 2
DEFEND_THE_SEAT_SEASONS = 3
SIEGE_SEASONS = 10

# How often the engine writes a stat snapshot for every living house. Five keeps
# a 300-season sparkline sixty points long and timeline.json well inside its
# size budget; hoc/export/timeline.py reads whatever spacing it finds.
SNAPSHOT_EVERY = 5

# The §6 season loop, phase by phase, in the order run_season runs them.
#
# A run always executes all of them; `PHASES` exists so that the two engines can
# be compared one phase at a time while `web/engine/sim.js` is being built or
# changed (`python -m hoc sim run --phases`, `node web/engine/cli.js --phases`).
# That flag is developer-only and is documented as such in both CLIs: a world
# played with a subset of phases is not a game, it is a diagnostic.
PHASES = (
    "clocks", "friction", "events", "mortality", "actions", "objectives",
    "debt", "founding", "enclosure",
)

# The pause conditions the director can arm a run with (§12, extended in 9e).
STOP_CONDITIONS = frozenset(
    {"removal", "challenge", "major", "marquis", "partition", "extinction"}
)

# How many chronicle lines a run summary carries. Enough to read what happened
# without pasting a whole season log into a workflow summary.
SUMMARY_CHRONICLE_LINES = 15


class SimError(Exception):
    """The engine cannot proceed: a malformed world, not a rules outcome."""


# ------------------------------------------------------------------- random --


def season_seed(world_seed, season_no):
    """A stable 32-bit seed for one season: fnv1a32("<world_seed>:<season_no>").

    Kept here as the engine's name for it; the algorithm lives in hoc.prng so
    that `web/engine/prng.js` has exactly one thing to mirror. Until Phase 10-1
    this digested the pair with blake2b, which was portable in principle and
    unavailable in JavaScript in practice.
    """
    return prng.season_seed(world_seed, season_no)


class LoggingRandom:
    """A seeded RNG that records every draw it is asked for.

    Each call appends `{purpose, result}` to the season log, which is what makes
    a season auditable: the log says not only what happened but which roll made
    it happen.

    Every method delegates to `hoc.prng.Prng`, whose draws are defined in terms
    of one 32-bit generator step and nothing else. Two rules hold here, and the
    cross-check enforces both (docs/DETERMINISM.md):

    * `weighted` takes an **ordered list of (key, integer weight) pairs**, never
      a mapping. The cumulative scan depends on the order it walks the options
      in, and a caller that passes a dict is trusting two languages' hash tables
      to agree about iteration order — which is exactly the kind of thing that
      holds for a hundred seasons and then does not.
    * `chance` takes an **integer per cent**, not a float. The one genuinely
      continuous probability in the game (§10's founding roll) goes through
      `chance_float` instead, and is the only float comparison the engine makes.
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
        return self._record(purpose, self.rng.rand_int(low, high))

    def chance(self, percent, purpose=None):
        """True with probability `percent`/100, from one integer draw.

        Logged as the roll and the verdict, because 'why did that house die' is
        the commonest question of a log. The roll is 1-100 and hits when it is
        less than or equal to the per cent, so 0 never fires and 100 always
        does.
        """
        percent = int(percent)
        roll = self.rng.rand_int(1, 100)
        return self._record(
            purpose, {"roll": roll, "pct": percent, "hit": roll <= percent}
        )["hit"]

    def chance_float(self, probability, purpose=None):
        """True with a continuous probability, compared against rand_float().

        Reserved for §10's founding roll. The logged roll is the raw float, so
        the season record shows the comparison that was actually made.
        """
        roll = self.rng.rand_float()
        return self._record(
            purpose, {"roll": roll, "p": probability, "hit": roll < probability}
        )["hit"]

    def die(self, sides=6, purpose=None):
        return self._record(purpose, self.rng.rand_int(1, sides))

    def two_d6(self, purpose=None):
        a, b = self.rng.rand_2d6()
        return self._record(purpose, {"dice": [a, b], "total": a + b})["total"]

    def weighted(self, options, purpose=None):
        """Draw from an ordered sequence of (key, integer weight) pairs.

        Zero and negative weights never come up. Returns None — and logs it —
        when nothing has a positive weight, which is a real outcome: a house
        with no legal action takes none.
        """
        pairs = list(options)
        keys = [key for key, _ in pairs]
        weights = [int(weight) for _, weight in pairs]
        return self._record(purpose, self.rng.weighted_choice(keys, weights))


def clamp(value, low, high):
    return max(low, min(high, value))


def canonical_json(obj):
    """The one way this repo serialises a season log.

    Sorted keys, no spaces after the separators, UTF-8 as written rather than
    escaped, and a single trailing newline. Two engines can only be compared
    byte for byte if they agree on the bytes, and "whatever json.dumps does by
    default" is not an agreement — it is two defaults that happen to match.

    `ensure_ascii=False` means the é in a Québécois place name is written as
    itself; `web/engine/cli.js` writes the same character, since JSON.stringify
    does not escape non-ASCII either.
    """
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"


# -------------------------------------------------------------------- world --


class World:
    """One scenario, played by the engine against an open connection.

    Nothing here commits: the caller owns the transaction, exactly as the v1
    turn runner does, so a season that fails part-way leaves the database as it
    was.
    """

    def __init__(self, conn, rules=None, world_seed=None, seasons_dir=None, phases=None,
                 rules_version=None, reference_dir=None):
        self.conn = conn
        # The reference-data set this world's map came from, and so the one its
        # designation tables must come from too: the database records it
        # (scripts/load_seed.py), so a World never infers it from a scenario.
        self.reference_dir = (
            Path(reference_dir) if reference_dir is not None
            else places.reference_dir_for(conn)
        )
        # Per-riding statistics and jurisdictions by year, where the set has
        # them (meridian-v1.0.3). Held so both engines load them — the
        # JavaScript engine's are web/engine/adjacency.js's ReferenceMap
        # ridingStats and ridingJurisdictions — and nothing in the season loop
        # reads them yet.
        self.riding_stats = places.riding_stats(self.reference_dir)
        self.riding_jurisdictions = places.riding_jurisdictions(self.reference_dir)
        # A world plays under one version of the rules. `rules_version` names it
        # when replaying a season that recorded one; otherwise it is whatever
        # rules/current.txt says now. `use_rules_version` switches mid-replay,
        # for a record that spans a version change.
        self.rules = rules or load_rules(version=rules_version)
        self.rules_version = self.rules.version or rules_version or RULES_VERSION
        # Which phases of the §6 loop to run. None means all of them, which is
        # the only configuration a real game is ever played in; a subset is a
        # developer's cross-check diagnostic (see PHASES).
        self.phases = frozenset(PHASES if phases is None else phases)
        unknown = self.phases - set(PHASES)
        if unknown:
            raise SimError(
                f"unknown phase(s) {', '.join(sorted(unknown))};"
                f" valid phases are {', '.join(PHASES)}"
            )
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
        self._noticed = set()

        self._index_rules()

    def _index_rules(self):
        """The lookups derived from the rules bundle.

        Rebuilt whenever the bundle changes, because a replay that crossed a
        version boundary while still holding the previous version's action table
        would play a game neither version describes.
        """
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

    def feature(self, name):
        """Whether the version this world is playing under turns on a behaviour."""
        return self.rules.feature(name)

    # -- rules 0.9: the atlas a house reads, and what its ground is worth --

    def opens_year(self, fed_id):
        """The personal year from which a riding is open to a house, from
        riding_stats.csv. A set without the column (ne-2026) opens everything
        at FOUNDING_YEAR."""
        stats = self.riding_stats.get(fed_id)
        if not stats or "opens_year" not in stats:
            return FOUNDING_YEAR
        return stats["opens_year"]

    def riding_open(self, fed_id, personal_year):
        """Whether a house at `personal_year` may take the riding. Always true
        unless `atlas_jurisdiction` is on."""
        if not self.feature("atlas_jurisdiction"):
            return True
        return personal_year >= self.opens_year(fed_id)

    def foundable(self, fed_id):
        """Whether the Crown may seat a new house here. A new house's clock
        reads FOUNDING_YEAR, so this is `riding_open` at that year."""
        return self.riding_open(fed_id, FOUNDING_YEAR)

    def closed_message(self, fed_id, who, personal_year):
        """The refusal a director sees for a closed riding: the riding, the
        house's personal year, and the riding's opens_year."""
        return (
            f"{self._riding_name(fed_id)} is closed to {who}: personal year"
            f" {personal_year} is before its opens_year {self.opens_year(fed_id)}"
        )

    def wealth_offset(self, fed_id):
        """wealth_tier − 3 under `riding_endowments`, else 0. A set without
        riding_stats.csv reads every riding as the neutral tier."""
        if not self.feature("riding_endowments"):
            return 0
        stats = self.riding_stats.get(fed_id) or {}
        return stats.get("wealth_tier", NEUTRAL_WEALTH_TIER) - NEUTRAL_WEALTH_TIER

    def jurisdiction_name(self, fed_id, year):
        """The name of the jurisdiction the riding lay under in `year`, from
        riding_jurisdictions.csv, or None where the set has no spans for it.
        Display only: the engine keys on ridings.csv's province code."""
        for span in self.riding_jurisdictions.get(fed_id, ()):
            if span["from_year"] <= year and (span["to_year"] is None or year <= span["to_year"]):
                return span["name"]
        return None

    def _jurisdiction_suffix(self, fed_id, year):
        """" (Rupert's Land)" when a riding's jurisdiction in `year` is named
        differently from the one in force today, else "". Under
        `atlas_jurisdiction` only, so a 0.8 chronicle line reads as it did."""
        if not self.feature("atlas_jurisdiction"):
            return ""
        then = self.jurisdiction_name(fed_id, year)
        spans = self.riding_jurisdictions.get(fed_id, ())
        now = spans[-1]["name"] if spans else None
        return f" ({then})" if then is not None and then != now else ""

    # -- persistence of the world seed --

    def use_rules_version(self, version):
        """Play the next season under `version`, loading its tables if need be.

        A season file records the version it was played under; a replay reads
        that rather than assuming the current one. A file with no version
        recorded is from before versioning and is replayed under the version the
        world already holds.
        """
        if not version or version == self.rules_version:
            return self.rules
        self.rules = load_rules(version=version)
        self.rules_version = self.rules.version
        self._index_rules()
        return self.rules

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
            # By seat fed_id, not by seat name: fed_id is an ASCII code with one
            # obvious ordering, while riding names carry accents and em-dashes
            # whose collation is SQLite's business and would have to be matched
            # exactly by the JavaScript engine (docs/DETERMINISM.md).
            " ORDER BY s.founded_season, seat.fed_id, h.house"
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

    def open_expansion_targets(self, house):
        """expansion_targets, less any riding closed to the house at its own
        personal year (rules 0.9 `atlas_jurisdiction`). Filtered here, before
        any weight or draw, exactly as land adjacency is — so a closed riding
        never consumes a draw."""
        targets = self.expansion_targets(house)
        if not self.feature("atlas_jurisdiction"):
            return targets
        year = self.personal_year(house)
        return [fed_id for fed_id in targets if self.riding_open(fed_id, year)]

    def can_expand_into_open(self, house):
        """§7's Expand precondition: an unclaimed land-adjacent riding exists —
        under `atlas_jurisdiction`, one open to this house."""
        if not self.feature("atlas_jurisdiction"):
            return self.has_expansion_target(house)
        key = ("can_expand_open", house)
        if key not in self._turn_cache:
            self._turn_cache[key] = bool(self.open_expansion_targets(house))
        return self._turn_cache[key]

    def founding_room(self):
        """§10's p_found numerator: unclaimed ridings with a land neighbour —
        under `atlas_jurisdiction`, only those the Crown may grant, so p_found
        reaches zero when the foundable map is full."""
        if not self.feature("atlas_jurisdiction"):
            return self.unclaimed_land_adjacent_count()
        return sum(
            1 for row in self.conn.execute(
                "SELECT r.fed_id FROM ridings r"
                " WHERE NOT EXISTS (SELECT 1 FROM holdings h WHERE h.fed_id = r.fed_id"
                "                   AND h.released_event_id IS NULL)"
                "   AND EXISTS (SELECT 1 FROM adjacency a WHERE a.adjacency_type = 'land'"
                "               AND (a.fed_id_a = r.fed_id OR a.fed_id_b = r.fed_id))"
            )
            if self.foundable(row["fed_id"])
        )

    def expand_refusal(self, house):
        """Why forcing Expand on this house would be refused, or None.

        Refused only when every unclaimed land neighbour is closed to it at the
        personal year it will act in — next season's, one on from today's —
        so the message names a closed riding, that year, and the opens_year.
        A house with no unclaimed neighbour at all is not this refusal's
        business: the season refuses that as it always has."""
        if not self.feature("atlas_jurisdiction"):
            return None
        targets = self.expansion_targets(house)
        if not targets:
            return None
        year = self.personal_year(house) + 1
        if any(self.riding_open(fed_id, year) for fed_id in targets):
            return None
        return self.closed_message(targets[0], house, year)

    # Rules 0.8: where a house's territorial designation may come from, most
    # local first. Under 0.7 there was one source — the seat's province — so a
    # house seated in Halifax could be styled "of Kamloops"; these tiers are
    # what fixed that, and they are behind `local_designations` so a 0.7 season
    # still draws the way it did when it was played.
    #
    # Four tiers rather than one because the data is thin: Natural Earth
    # resolves 255 Canadian places, covering 111 of 343 ridings, so most seats
    # have no town of their own to be named for. The seat's *name* always
    # yields something, which is what makes the draw able to answer at all.
    DESIGNATION_TIERS = 4

    def _designation_tiers(self, fed_id, province):
        """Candidate designations for a seat, most local first.

        1. Places inside the seat riding, largest population first.
        2. The seat's own name, split into its usable words.
        3. Places in ridings that share a land border with the seat, in fed_id
           order — a neighbour, not a stranger three provinces away.
        4. The province bank rules 0.7 used, as a last resort.

        Land adjacency only, and for the same reason expansion uses it: two
        ridings across a strait are not neighbours in any sense a peerage would
        recognise.
        """
        by_riding = places.places_by_riding(self.reference_dir)
        by_tokens = places.tokens_by_riding(self.reference_dir)

        neighbours = [
            row["fed_id"] for row in self.conn.execute(
                "SELECT CASE WHEN fed_id_a = ? THEN fed_id_b ELSE fed_id_a END AS fed_id"
                " FROM adjacency WHERE adjacency_type = 'land' AND (fed_id_a = ? OR fed_id_b = ?)"
                " ORDER BY fed_id",
                (fed_id, fed_id, fed_id),
            )
        ]
        near = []
        for neighbour in neighbours:
            near.extend(by_riding.get(neighbour, ()))

        bank = [row.place for row in self.rules.places if row.province == province]
        return [
            list(by_riding.get(fed_id, ())),
            list(by_tokens.get(fed_id, ())),
            near,
            bank,
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
            # Who the chronicle mentioned this season, for rules 0.8's idle-house
            # line. Taken from the event's own house list rather than by looking
            # for a name in the prose: a title can appear inside another house's
            # line, and matching on text would notice the wrong house.
            self._noticed.update(houses or ())
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
        if self.feature("atlas_jurisdiction"):
            # Rules 0.9: "unclaimed" means unclaimed and foundable, so a region
            # with no seat left the Crown may grant has no room and no weight.
            for row in self.conn.execute(
                "SELECT r.fed_id, r.province FROM ridings r"
                " WHERE NOT EXISTS (SELECT 1 FROM holdings h WHERE h.fed_id = r.fed_id"
                "                   AND h.released_event_id IS NULL)"
                " ORDER BY r.fed_id"
            ):
                if self.foundable(row["fed_id"]):
                    capacity[PROVINCE_REGION.get(row["province"], "north")] += 1
        else:
            for row in self.conn.execute(
                "SELECT r.province, COUNT(*) AS n FROM ridings r"
                " WHERE NOT EXISTS (SELECT 1 FROM holdings h WHERE h.fed_id = r.fed_id"
                "                   AND h.released_event_id IS NULL)"
                " GROUP BY r.province"
            ):
                capacity[PROVINCE_REGION.get(row["province"], "north")] += row["n"]

        # Integer drift (rules 0.7): base * (20 + room) // 20 is the old float
        # form base * (1 + room/20) with the rounding made explicit. Regions are
        # walked in sorted name order so the cumulative scan never depends on
        # the order founding.json happens to list them in.
        weights = []
        for region in sorted(self.region_weights):
            room = capacity.get(region, 0)
            if room == 0:
                continue
            weights.append((region, self.region_weights[region] * (20 + room) // 20))
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
        candidates = [row["fed_id"] for row in rows if self.foundable(row["fed_id"])]
        if not candidates:
            return None
        return rng.choice(candidates, purpose="founding.seat")

    def _draw_tag(self, rng):
        """Tag with climate fit: the Confederation ledger's sign doubles the
        weight of the matching tag (§10)."""
        weights = {"Progressive": 200, "Conservative": 200, "Mixed": 200, "Outside": 100}
        try:
            climate = mechanics.current_climate(self.conn, "confederation")
        except mechanics.RuleError:
            climate = 0
        if climate > 0:
            weights["Progressive"] *= 2
        elif climate < 0:
            weights["Conservative"] *= 2
        # A fixed, written-out order: these four tags are the whole domain.
        return rng.weighted(
            [(tag, weights[tag]) for tag in ("Progressive", "Conservative", "Mixed", "Outside")],
            purpose="founding.tag",
        )

    def found_house(self, season, seat=None, rng=None, community=None, tag=None,
                    rank=None, surname=None):
        """Found a house (§10 and §4). Returns its name, or None if it cannot.

        `seat`, `community`, `tag`, `rank` and `surname` may each be the
        director's choice, through the console's grant (§12); anything left
        unspecified is drawn. Whatever the director fixes, the rest still comes
        from the tables and the season's RNG — a granted house is initialised by
        the same rules as one the founding roll produced, so it is not a
        privileged object on the map.
        """
        rng = rng or self.rng_for(season)
        self._initial_climate()

        if seat is not None:
            fed_id = self._resolve_riding(seat)
            if fed_id is None:
                raise SimError(f"unknown riding {seat!r}")
            if mechanics._holder_of(self.conn, fed_id) is not None:
                raise SimError(f"riding {seat!r} is already held")
            if not self.foundable(fed_id):
                raise SimError(self.closed_message(fed_id, "a new house", FOUNDING_YEAR))
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
            # rules/communities.csv row order, which is the file's own order.
            community_row = rng.weighted(
                [(c.community, c.weight) for c in pool], purpose="founding.community"
            )
        else:
            community_row = community
        community_obj = next(
            (c for c in pool if c.community == community_row),
            next(c for c in self.rules.communities if c.community == community_row),
        )

        tag = tag or self._draw_tag(rng)
        rank = rank or rng.weighted(
            # Ordered up the rank ladder (Baron, Viscount, Earl, ...) rather
            # than by whatever order founding.json lists them in.
            sorted(
                self.rules.founding["rank_probabilities"].items(),
                key=lambda pair: (self.rank_index.get(pair[0], 0), pair[0]),
            ),
            purpose="founding.rank",
        )
        rank_index = self.rank_index.get(rank, 0)

        generator = NameGenerator(self.rules, rng)
        tiers = self._designation_tiers(fed_id, province) \
            if self.feature("local_designations") else None
        try:
            drawn = generator.draw_house(
                community_obj.community, province, rank,
                taken_places=self.taken_places(), surname=surname or None, tiers=tiers,
            )
        except Exception as exc:  # a bank that cannot serve this province
            self.log.append({"purpose": "founding.abandoned", "result": str(exc)})
            return None
        if drawn["tier"] is not None:
            # Which tier answered. Recorded because it is the only way to tell,
            # from the log alone, whether the local tiers are doing any work —
            # tests/test_designations.py measures exactly this over a long run.
            self.log.append({
                "purpose": "founding.designation",
                "result": {"tier": drawn["tier"], "place": drawn["place"]},
            })

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

        # Rules 0.9 `riding_endowments`: + 2*(wealth_tier - 3) of the seat,
        # added after the draw so the draw order is the one 0.8 made.
        stats = {
            "capital": clamp(
                30 + 5 * rank_index + rng.randint(1, 20, "founding.capital")
                + 2 * self.wealth_offset(fed_id),
                *STAT_RANGE,
            ),
            "influence": clamp(20 + 5 * rank_index + rng.randint(1, 20, "founding.influence"), *STAT_RANGE),
            "cohesion": clamp(60 + rng.randint(1, 20, "founding.cohesion"), *STAT_RANGE),
            "ambition": clamp(rng.randint(1, 10, "founding.ambition"), *AMBITION_RANGE),
        }
        self.conn.execute(
            "INSERT INTO house_stats (house, capital, influence, cohesion, ambition, enclosed,"
            " community, region, tradition, tag, province, seat_place, founded_season,"
            " founded_by)"
            " VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, 'crown')",
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
        cursor = self.conn.execute(
            "INSERT INTO persons (house, name, gender, age, role, alive, born_season)"
            " VALUES (?, ?, ?, ?, 'holder', 1, ?)",
            (house, f"{drawn['given']} {drawn['surname']}", drawn["gender"], holder_age, season),
        )
        # Rules 1.0 `holder_traits`: the founding holder's two traits.
        traits = self._give_traits(cursor.lastrowid, house, rng)
        self.conn.execute(
            "INSERT INTO clocks (house, personal_year, basis) VALUES (?, 1867, ?)",
            (house, f"founded season {season}"),
        )

        founding_delta = {"stats": stats, "community": community_obj.community, "tag": tag}
        if traits:
            founding_delta["traits"] = traits
        seat_jurisdiction = (
            self.jurisdiction_name(fed_id, FOUNDING_YEAR)
            if self.feature("atlas_jurisdiction") else None
        )
        if seat_jurisdiction is not None:
            # Display only (rules 0.9): the seat's jurisdiction at the new
            # house's personal year, in the event and in the season's log.
            founding_delta["jurisdiction"] = seat_jurisdiction
            self.log.append({
                "purpose": "founding.jurisdiction",
                "result": {"riding": self._riding_name(fed_id), "jurisdiction": seat_jurisdiction},
            })
        event_id = self.record(
            "founding",
            f"{drawn['peerage']} founded",
            [house],
            season,
            band="confederation",
            line=f"Season {season} · {drawn['peerage']} is created, seated at "
                 f"{self._riding_name(fed_id)}"
                 f"{self._jurisdiction_suffix(fed_id, FOUNDING_YEAR)}.",
            delta=founding_delta,
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
        # Integer weights at WEIGHT_SCALE: an unfavoured objective is 1, a
        # favoured one 3, exactly as the old 1.0 + 2.0*favoured said.
        weights = [
            (
                objective.objective,
                WEIGHT_SCALE
                + 2 * WEIGHT_SCALE * self._objective_favoured(objective.objective, row, house),
            )
            for objective in self.rules.objectives
        ]
        for _ in range(OBJECTIVES_AT_FOUNDING):
            held = set(self.held_objectives(house))
            available = [(name, weight) for name, weight in weights if name not in held]
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

        percent = probability_for_age(self.rules.mortality, holder["age"])
        rolls = 2 if extra_roll else 1
        # `any` short-circuits, so a house that dies on the first roll never
        # draws the second. That is deliberate and both engines must do it: the
        # alternative would consume a draw the log has no outcome for.
        died = any(
            rng.chance(percent, purpose=f"mortality.{house}") for _ in range(rolls)
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
            # Rules 1.0 `holder_traits`: the heir's traits were drawn when the
            # heir was named; one named before they were draws them now.
            heir_traits = self._ensure_traits(heir["id"], house, rng)
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
                delta=self._with_traits({"nature": "clean", "cause": cause}, heir_traits),
            )
            self._reconsider_scheme(house, season)
            return self._check_extinction(house, season, rng)

        # Disorderly: no heir named.
        succession = self.rules.succession["disorderly_succession"]
        self.set_stats(
            house,
            cohesion=succession["cohesion_delta"],
            capital=succession["capital_delta"],
        )
        if rng.chance(NO_SUCCESSOR_PCT, purpose=f"succession.no_successor.{house}"):
            self._remove_house(house, season, reason="no successor", rng=rng)
            return True

        community = row["community"]
        generator = NameGenerator(self.rules, rng)
        given, surname, gender = generator.draw_person(community, surname=house.split(" ")[0])
        age = 35 + rng.randint(1, 20, "succession.successor_age")
        cursor = self.conn.execute(
            "INSERT INTO persons (house, name, gender, age, role, alive, born_season)"
            " VALUES (?, ?, ?, ?, 'holder', 1, ?)",
            (house, f"{given} {surname}", gender, age, season),
        )
        successor_traits = self._give_traits(cursor.lastrowid, house, rng)
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
            delta=self._with_traits({"nature": "disorderly", "cause": cause}, successor_traits),
        )

        # §9: a disorderly succession sours a neighbour.
        neighbours = self.neighbouring_houses(house)
        percent = self.rules.succession["disorderly_succession"]["sig_minus_probability_pct"]
        if neighbours and rng.chance(percent, purpose=f"succession.grievance.{house}"):
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
            loss["probability_pct"], purpose=f"succession.riding_loss.{house}"
        ):
            self._lose_riding(house, season, reason="disorderly succession")

        self._reconsider_scheme(house, season)
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
        # A cadet line is seated on the outermost riding the parent gives up, so
        # its designation is drawn from *that* riding's ground, not the parent's.
        try:
            if self.feature("local_designations"):
                tier, place = generator.draw_designation(
                    self._designation_tiers(outer[0]["fed_id"], province), self.taken_places()
                )
                self.log.append({
                    "purpose": "partition.designation",
                    "result": {"tier": tier, "place": place},
                })
            else:
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
            " community, region, tradition, tag, province, seat_place, founded_season,"
            " founded_by)"
            " VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, 'partition')",
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
        # Rules 1.0 `holder_traits`: a junior heir named before traits were
        # drawn for heirs draws them on taking the cadet seat.
        self._ensure_traits(junior["id"], cadet, rng)
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
        self._end_schemes_of(house, season)

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
            self._tally(house, lost=1)
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
        # Rules 1.0 `holder_traits`: a steadfast holder (Zealot) never stands aside.
        if response == "Neutral" and self._trait_effect(house, "steadfast"):
            response = "Resist"

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

    # ------------------------------------------------------------- rules 1.0 --
    #
    # docs/STORY_DESIGN.md §4. Every behaviour here is behind its own flag and
    # mirrored line for line in web/engine/sim.js.

    def _marriable(self, house):
        """Rules 1.0 `marriage_pairing`: a house's unmarried heirs and children,
        by person id — everyone living in it but the holder who has not married."""
        return self.conn.execute(
            "SELECT * FROM persons WHERE house = ? AND alive = 1 AND married = 0"
            " AND role IN ('heir', 'heir2', 'other') ORDER BY id",
            (house,),
        ).fetchall()

    def _marriage_pair(self, house, other):
        """One man and one woman, by recorded gender, one from each house: the
        first such pair taking this house's people by id, then the other's."""
        theirs_all = self._marriable(other)
        for mine in self._marriable(house):
            for theirs in theirs_all:
                if {mine["gender"], theirs["gender"]} == {"m", "f"}:
                    return mine, theirs
        return None

    def _traits_of(self, person):
        return [t for t in ((person["traits"] if person else None) or "").split(",") if t]

    def _holder_trait_rows(self, house):
        """The rules rows of the holder's traits, under `holder_traits`."""
        if not self.feature("holder_traits"):
            return []
        names = self._traits_of(self.holder(house))
        return [t for t in self.rules.traits if t.trait in names]

    def _trait_effect(self, house, effect):
        """The sum of a named effect over the holder's traits (0 without the flag)."""
        return sum(t.effects.get(effect, 0) for t in self._holder_trait_rows(house))

    def _draw_traits(self, house, rng):
        """Two traits from traits.csv, in its row order: the first from all of
        them, the second from those neither excluding nor excluded by it."""
        names = [t.trait for t in self.rules.traits]
        if not names:
            return []
        first = rng.choice(names, purpose=f"traits.{house}")
        row = next(t for t in self.rules.traits if t.trait == first)
        rest = [
            t.trait for t in self.rules.traits
            if t.trait != first and t.trait not in row.excludes and first not in t.excludes
        ]
        if not rest:
            return [first]
        return [first, rng.choice(rest, purpose=f"traits.{house}")]

    def _give_traits(self, person_id, house, rng):
        """Draw and record a person's traits under `holder_traits`."""
        if not self.feature("holder_traits"):
            return []
        traits = self._draw_traits(house, rng)
        self.conn.execute(
            "UPDATE persons SET traits = ? WHERE id = ?", (",".join(traits), person_id)
        )
        return traits

    def _ensure_traits(self, person_id, house, rng):
        """A new holder's traits: those drawn when they were named, or drawn now."""
        if not self.feature("holder_traits"):
            return []
        row = self.conn.execute("SELECT * FROM persons WHERE id = ?", (person_id,)).fetchone()
        return self._traits_of(row) or self._give_traits(person_id, house, rng)

    def _with_traits(self, delta, traits):
        if traits:
            delta = dict(delta)
            delta["traits"] = traits
        return delta

    def _upkeep(self, house):
        """Rules 1.0 `upkeep_phase` (§4.1): the turn's automatic upkeep."""
        spec = self.rules.upkeep
        row = self.house_row(house)
        holdings = self.holdings(house)
        capital = spec["capital"]["base"] + len(holdings) // spec["capital"]["holdings_per_point"]
        if holdings:
            capital += self.wealth_offset(holdings[0]["fed_id"])
        influence = spec["influence"]["base"]
        cohesion = spec["cohesion"]["base"]
        if row["cohesion"] < spec["cohesion"]["recovery_below"]:
            cohesion += spec["cohesion"]["recovery"]
        for trait in self._holder_trait_rows(house):
            capital += trait.upkeep.get("capital", 0)
            influence += trait.upkeep.get("influence", 0)
            cohesion += trait.upkeep.get("cohesion", 0)
        self.log.append({
            "purpose": f"upkeep.{house}",
            "result": {"capital": capital, "influence": influence, "cohesion": cohesion},
        })
        self.set_stats(house, capital=capital, influence=influence, cohesion=cohesion)

    _letter_mode = False

    def _letter_delta(self, delta):
        """A correspondence event's delta, marked when it is an automatic letter."""
        if self._letter_mode:
            delta = dict(delta)
            delta["letter"] = True
        return delta

    def _letter(self, house, season, rng):
        """Rules 1.0 `upkeep_phase`: one automatic correspondence draw a turn,
        resolved exactly as the Correspond action was, offence included."""
        if not self.houses_within_reach(house):
            return None
        if not rng.chance(self.rules.upkeep["correspondence_pct"], purpose=f"letter.{house}"):
            return None
        roll = rng.two_d6(purpose=f"resolve.Correspond.{house}")
        success = roll >= self.actions["Correspond"].target
        band = self.band_for(self.personal_year(house))
        self._letter_mode = True
        try:
            return self._do_correspond(house, season, rng, success, band, roll)
        finally:
            self._letter_mode = False

    def _record_of_age(self, house, name, age, season, band):
        row = self.house_row(house)
        self.record(
            "other",
            f"{row['peerage']}: an heir comes of age",
            [house],
            season,
            band=band,
            line=f"Season {season} · {name}, heir to {row['peerage']}, comes of age.",
            delta={"watch": "heir_of_age", "heir_age": age},
        )

    def _succession_watch(self, house, season):
        """Rules 1.0 `succession_watch` (§4.8): a holder turning sixty with no
        heir named, and an heir coming of age, each recorded once."""
        spec = self.rules.succession["watch"]
        holder = self.holder(house)
        band = self.band_for(self.personal_year(house))
        if holder is not None and holder["age"] == spec["holder_age"] and not self.heirs(house):
            row = self.house_row(house)
            self.record(
                "other",
                f"{row['peerage']}: no heir at {spec['holder_age']}",
                [house],
                season,
                band=band,
                line=f"Season {season} · {holder['name']} of {row['peerage']} turns"
                     f" {spec['holder_age']} with no heir named.",
                delta={"watch": "no_heir", "age": spec["holder_age"]},
            )
        for heir in self.heirs(house):
            if heir["role"] == "heir" and heir["age"] == spec["heir_of_age"]:
                self._record_of_age(house, heir["name"], heir["age"], season, band)

    def _tally(self, house, won=0, lost=0):
        """Rules 1.0 `prestige`: the contests a house has won and the ridings it
        has lost to another house. Kept only under the flag."""
        if not self.feature("prestige"):
            return
        self.conn.execute(
            "UPDATE house_stats SET contests_won = contests_won + ?,"
            " ridings_lost = ridings_lost + ? WHERE house = ?",
            (won, lost, house),
        )

    def _compute_prestige(self, season):
        """Rules 1.0 `prestige` (§4.5): 10 per holding, 20 per rank index,
        influence // 5, 5 per compact or kin tie with an active house, 15 per
        dispute or challenge won, -15 per riding lost to another house."""
        out = {}
        for row in self.active_houses():
            house = row["house"]
            stats = self.house_row(house)
            ties = self.conn.execute(
                "SELECT COUNT(*) AS n FROM relations r"
                " JOIN houses o ON o.house = CASE WHEN r.house_a = ? THEN r.house_b ELSE r.house_a END"
                " WHERE (r.house_a = ? OR r.house_b = ?) AND r.marker IN (?, ?)"
                " AND o.status = 'active'",
                (house, house, house, COMPACT, KIN),
            ).fetchone()["n"]
            value = (
                10 * self.holding_count(house)
                + 20 * self.rank_index.get(stats["rank"], 0)
                + stats["influence"] // 5
                + 5 * ties
                + 15 * stats["contests_won"]
                - 15 * stats["ridings_lost"]
            )
            out[house] = value
            self.conn.execute(
                "UPDATE house_stats SET prestige = ? WHERE house = ?", (value, house)
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO prestige_history (season_no, house, value) VALUES (?, ?, ?)",
                (season, house, value),
            )
        return out

    def _founding_curve_roll(self, season, rng):
        """Rules 1.0 `founding_curve` (§4.6): the Crown founds a house at the
        schedule's integer per cent for this season, while foundable land is
        left, and after `late_after` never within `late_gap` seasons of its
        last founding."""
        spec = self.rules.founding["founding_curve"]
        pct = 0
        for row in spec["schedule"]:
            if row["through"] is None or season <= row["through"]:
                pct = row["pct"]
                break
        room = self.founding_room()
        last = self.conn.execute(
            "SELECT MAX(founded_season) AS n FROM house_stats WHERE founded_by = 'crown'"
        ).fetchone()["n"]
        if season > spec["late_after"] and last is not None and season - last < spec["late_gap"]:
            pct = 0
        rng.draw("founding.curve", {"room": room, "pct": pct})
        if room <= 0 or pct <= 0:
            return None
        if not rng.chance(pct, purpose="founding.roll"):
            return None
        return self.found_house(season, rng=rng)

    # ------------------------------------------------------------- phase C2 --
    #
    # docs/STORY_DESIGN.md §4.2 (`schemes`), §4.4 (`contested_claims`), §4.5
    # (`prestige_politics`) and §4.9 (`cohesion_strain`). Every behaviour is
    # behind its flag and mirrored line for line in web/engine/sim.js. A scheme
    # is a row of the schemes table; its rules are a row of schemes.csv and the
    # numbers in schemes.json.

    # Set while a scheme resolves through an action handler: `_pick` then
    # takes the scheme's named target instead of drawing one, and a Dispute
    # pressed as Break a rival hardens on success.
    _scheme_target = None

    def _strain(self, house):
        """Rules 1.0 `cohesion_strain` (§4.9): -1 cohesion for each holding
        beyond free_holdings + per_rank_index x rank index, and -1 while the
        holder is older than holder_over."""
        spec = self.rules.upkeep["strain"]
        row = self.house_row(house)
        free = spec["free_holdings"] + spec["per_rank_index"] * self.rank_index.get(row["rank"], 0)
        loss = max(0, self.holding_count(house) - free)
        holder = self.holder(house)
        if holder is not None and holder["age"] > spec["holder_over"]:
            loss += 1
        self.log.append({"purpose": f"strain.{house}", "result": loss})
        if loss:
            self.set_stats(house, cohesion=-loss)

    def standing(self, house):
        """What a house is worth to the others: its prestige as last computed
        under `prestige`, else 10 per holding and 20 per rank index."""
        row = self.house_row(house)
        if self.feature("prestige") and row["prestige"] is not None:
            return row["prestige"]
        return 10 * self.holding_count(house) + 20 * self.rank_index.get(row["rank"], 0)

    def _ranking(self):
        """(the leader, the top houses) by standing, ties by name. Cached for
        the house's turn; read only before anything in the turn moves."""
        if "ranking" not in self._turn_cache:
            top = self.rules.scheme_rules["utility"]["top"]
            ranked = sorted((-self.standing(r["house"]), r["house"]) for r in self.active_houses())
            names = [house for _, house in ranked]
            self._turn_cache["ranking"] = (names[0] if names else None, set(names[:top]))
        return self._turn_cache["ranking"]

    def _scheme_spec(self, name):
        return next((s for s in self.rules.schemes if s.scheme == name), None)

    def _contest_schemes(self):
        return [s.scheme for s in self.rules.schemes if s.resolves_as == "contest"]

    def active_scheme(self, house):
        return self.conn.execute(
            "SELECT * FROM schemes WHERE house = ? AND status = 'active' ORDER BY id LIMIT 1",
            (house,),
        ).fetchone()

    def _scheme(self, scheme_id):
        return self.conn.execute("SELECT * FROM schemes WHERE id = ?", (scheme_id,)).fetchone()

    def _wealth_tier(self, fed_id):
        stats = self.riding_stats.get(fed_id) or {}
        return stats.get("wealth_tier", NEUTRAL_WEALTH_TIER)

    def _is_seat(self, house, fed_id):
        row = self.conn.execute(
            "SELECT seat_order FROM holdings WHERE house = ? AND fed_id = ?"
            " AND released_event_id IS NULL",
            (house, fed_id),
        ).fetchone()
        return row is not None and row["seat_order"] == 1

    def _has_trait(self, house, trait):
        return any(t.trait == trait for t in self._holder_trait_rows(house))

    def _claim_targets(self, house):
        """Every (house, fed_id) another active house holds land-adjacent to
        one of this house's ridings, by house and then fed_id."""
        return [
            (row["house"], row["fed_id"])
            for row in self.conn.execute(
                "SELECT DISTINCT theirs.house AS house, theirs.fed_id AS fed_id FROM holdings mine"
                " JOIN adjacency a ON a.adjacency_type = 'land'"
                "   AND (a.fed_id_a = mine.fed_id OR a.fed_id_b = mine.fed_id)"
                " JOIN holdings theirs ON theirs.released_event_id IS NULL"
                "   AND theirs.fed_id = CASE WHEN a.fed_id_a = mine.fed_id"
                "                            THEN a.fed_id_b ELSE a.fed_id_a END"
                " JOIN houses h ON h.house = theirs.house AND h.status = 'active'"
                " WHERE mine.house = ? AND mine.released_event_id IS NULL"
                "   AND theirs.house <> ?"
                " ORDER BY theirs.house, theirs.fed_id",
                (house, house),
            )
        ]

    def _contest_cooldown(self, house_a, house_b, season):
        """Whether the pair met in a contest within schemes.json's cooldown."""
        row = self.conn.execute(
            "SELECT MAX(ended_season) AS n FROM schemes WHERE status = 'resolved'"
            " AND outcome IN ('won', 'held')"
            " AND ((house = ? AND target_house = ?) OR (house = ? AND target_house = ?))",
            (house_a, house_b, house_b, house_a),
        ).fetchone()
        cooldown = self.rules.scheme_rules["contest"]["cooldown"]
        return row["n"] is not None and season - row["n"] < cooldown

    def _lost_contest(self, house, season, other=None):
        """Whether the house lost a contest (to `other`, if named) within
        utility.recent_loss_turns."""
        window = self.rules.scheme_rules["utility"]["recent_loss_turns"]
        for row in self.conn.execute(
            "SELECT house, target_house, outcome FROM schemes WHERE status = 'resolved'"
            " AND outcome IN ('won', 'held') AND ended_season >= ?"
            " AND (house = ? OR target_house = ?) ORDER BY id",
            (season - window, house, house),
        ):
            if row["house"] == house and row["outcome"] == "held":
                winner = row["target_house"]
            elif row["target_house"] == house and row["outcome"] == "won":
                winner = row["house"]
            else:
                continue
            if other is None or winner == other:
                return True
        return False

    def _claims_on(self, house, by=None):
        """Active claims (contest schemes) against this house, by id."""
        names = self._contest_schemes()
        if not names:
            return []
        marks = ",".join("?" for _ in names)
        rows = self.conn.execute(
            f"SELECT * FROM schemes WHERE status = 'active' AND target_house = ?"
            f" AND scheme IN ({marks}) ORDER BY id",
            (house, *names),
        ).fetchall()
        return [r for r in rows if by is None or r["house"] == by]

    def _relation_age(self, house_a, house_b, season):
        made = self._relation_season(house_a, house_b)
        return None if made is None else season - made

    def _peace_waits(self, house, other, season):
        """A grievance cannot be reconciled or settled in its first turns."""
        if self.relation_marker(house, other) != GRIEVANCE:
            return False
        age = self._relation_age(house, other, season)
        return age is not None and age < self.rules.scheme_rules["peace"]["wait"]

    def _can_name_heir(self, house):
        """§7's Name heir precondition, as legal_actions states it."""
        holder = self.holder(house)
        if holder is None or holder["age"] < 45:
            return False
        existing = self.heirs(house)
        second = self.rules.succession["heirs"]
        if not existing:
            return True
        return (
            len(existing) == 1
            and existing[0]["age"] >= second["second_heir_min_age"]
            and self.holding_count(house) >= second["second_heir_min_holdings"]
        )

    def _match_candidates(self, house):
        """The houses a Marriage alliance could bind this one to now."""
        pairing = self.feature("marriage_pairing")
        if not pairing and not self._unmarried_heir(house):
            return []
        return [
            other for other in self.houses_related_by(house, {FRIENDLY, COMPACT})
            if (self._marriage_pair(house, other) if pairing else self._unmarried_heir(other))
        ]

    def _compact_candidates(self, house):
        row = self.house_row(house)
        return [
            other for other in self.houses_related_by(house, {FRIENDLY})
            if self.house_row(other)["tag"] == row["tag"]
            or "Mixed" in (row["tag"], self.house_row(other)["tag"])
        ]

    def _dispute_candidates(self, house, season):
        return [
            other for other in self.houses_related_by(house, {GRIEVANCE})
            if self._adjacent_holding_of(house, other)
            and not self._dispute_blocked(house, other, season)
        ]

    def _step_cost(self, house, spec, target_house):
        """(capital, influence) one step commits. A claim on a house this one
        already has a quarrel with costs less (utility.claim_discount)."""
        capital, influence = spec.step_capital, spec.step_influence
        if spec.resolves_as == "contest" and target_house is not None \
                and self.relation_marker(house, target_house) in (GRIEVANCE, HOSTILE):
            capital = max(0, capital - self.rules.scheme_rules["utility"]["claim_discount"])
        return capital, influence

    def _affords(self, house, spec, target_house, extra_capital=0):
        row = self.house_row(house)
        capital, influence = self._step_cost(house, spec, target_house)
        return row["capital"] >= capital + extra_capital and row["influence"] >= influence

    def scheme_utility(self, house, spec, target_house, target_riding, season):
        """Rules 1.0 `schemes` (§4.2): one scheme's integer utility for this
        house, from its situation, objectives, holder traits, the target
        riding's wealth tier and, under `prestige_politics`, prestige."""
        terms = self.rules.scheme_rules["utility"]
        row = self.house_row(house)
        value = spec.utility
        for objective in self.held_objectives(house):
            o = self.objectives.get(objective)
            if o is None:
                continue
            value += terms["objective"] * sum(1 for a in spec.reads if a in o.action_weight_bonus)
        for trait in self._holder_trait_rows(house):
            for action in spec.reads:
                value += trait.actions.get(action, 0) * terms["trait_unit"]
        kind = spec.resolves_as
        if kind in ("contest", "frontier", "Purchase riding", "Dispute"):
            value += row["ambition"] * terms["ambition"]
            if row["cohesion"] < terms["low_cohesion"]:
                value -= terms["low_cohesion_penalty"]
        if target_riding is not None and kind in ("contest", "frontier"):
            value += terms["wealth_tier"] * self._wealth_tier(target_riding)
        if kind == "contest":
            marker = self.relation_marker(house, target_house)
            if marker == GRIEVANCE:
                value += terms["grievance"]
            elif marker == HOSTILE:
                value += terms["hostile"]
            if self.standing(target_house) < self.standing(house):
                value += terms["weaker_target"]
            if self._is_seat(target_house, target_riding):
                value += terms["seat"]
            if self.feature("prestige_politics"):
                if self.house_row(target_house)["cohesion"] < terms["low_cohesion"] \
                        or self._lost_contest(target_house, season):
                    value += terms["weak_target"]
                leader, top = self._ranking()
                if target_house == leader and house != leader and house in top:
                    value += terms["leader_target"]
        elif kind == "Petition elevation":
            value += max(0, (row["influence"] - terms["elevation_influence_from"]) // 5)
        elif kind == "Name heir":
            holder = self.holder(house)
            if holder is not None:
                value += max(0, holder["age"] - terms["line_age_from"])
        elif kind == "Propose compact":
            if self._claims_on(house):
                value += terms["under_claim"]
            if self.feature("prestige_politics"):
                gap = self.standing(target_house) - self.standing(house)
                value += min(terms["protector_gap_max"], max(0, gap) // terms["protector_per_gap"])
                leader, _ = self._ranking()
                if target_house == leader:
                    value += terms["leader_ally"]
        elif kind == "Reconcile":
            if (
                self._claims_on(house, by=target_house)
                or self._lost_contest(house, season, target_house)
                or row["cohesion"] < terms["low_cohesion"]
                or self._has_trait(house, "Conciliator")
            ):
                value += terms["peace_cause"]
        elif kind == "sue":
            if self.standing(house) < self.standing(target_house):
                value += terms["weaker_target"]
            if row["cohesion"] < terms["low_cohesion"]:
                value += terms["low_cohesion_penalty"]
        elif kind == "fortify":
            if self._is_seat(house, target_riding):
                value -= terms["seat"]
        return value

    def _scheme_targets(self, house, spec, season, claim=None):
        """The (target house, target riding) pairs a scheme could be begun
        on now, in a fixed order; empty when it cannot be begun at all."""
        kind = spec.resolves_as
        row = self.house_row(house)
        if kind == "contest":
            if not self.feature("contested_claims"):
                return []
            out = []
            for other, fed_id in self._claim_targets(house):
                if claim is not None and other != claim["house"]:
                    continue
                if self.relation_marker(house, other) in (KIN, COMPACT):
                    continue
                if self._contest_cooldown(house, other, season):
                    continue
                if self._affords(house, spec, other):
                    out.append((other, fed_id))
            return out
        if kind == "frontier":
            return [
                (None, fed_id) for fed_id in self.open_expansion_targets(house)
                if self._affords(house, spec, None, 15 + self.wealth_offset(fed_id))
            ]
        if kind == "Purchase riding":
            if row["capital"] < 70 or not self._affords(house, spec, None):
                return []
            return [(other, None) for other in self._purchase_targets(house)]
        if kind == "Dispute":
            if not self._affords(house, spec, None):
                return []
            return [(other, None) for other in self._dispute_candidates(house, season)]
        if kind == "Marriage alliance":
            if not self._affords(house, spec, None):
                return []
            return [(other, None) for other in self._match_candidates(house)]
        if kind == "Petition elevation":
            if (
                row["influence"] >= 60 and self.holding_count(house) >= 3
                and self.rank_index.get(row["rank"], 0) < self.rank_index["Marquis"]
                and self._affords(house, spec, None)
            ):
                return [(None, None)]
            return []
        if kind == "Propose compact":
            if not self._affords(house, spec, None):
                return []
            mine = self.standing(house)
            return [
                (other, None) for other in self._compact_candidates(house)
                if self.standing(other) > mine
            ]
        if kind == "Name heir":
            return [(None, None)] if self._can_name_heir(house) and self._affords(house, spec, None) else []
        if kind == "Reconcile":
            if not self._affords(house, spec, None):
                return []
            return [
                (other, None) for other in self.houses_related_by(house, {GRIEVANCE, HOSTILE})
                if not self._peace_waits(house, other, season)
            ]
        if kind == "fortify":
            if claim is None or not self._affords(house, spec, None):
                return []
            return [(claim["house"], claim["target_riding"])]
        if kind == "sue":
            if claim is None or not self._affords(house, spec, None) \
                    or self._peace_waits(house, claim["house"], season):
                return []
            return [(claim["house"], None)]
        return []

    def _scheme_candidates(self, house, season, claim=None):
        """(utility, row index, target house, target riding, spec) for every
        scheme the house could begin now — or, given a claim against it, every
        answer it could make."""
        out = []
        for index, spec in enumerate(self.rules.schemes):
            if claim is None and spec.answer == "only":
                continue
            if claim is not None and spec.answer == "no":
                continue
            for target_house, target_riding in self._scheme_targets(house, spec, season, claim):
                value = self.scheme_utility(house, spec, target_house, target_riding, season)
                out.append((value, index, target_house or "", target_riding or "", spec))
        return out

    @staticmethod
    def _candidate_key(candidate):
        spec = candidate[4]
        return f"{spec.scheme if spec else 'Stand'}|{candidate[2]}|{candidate[3]}"

    def _choose_scheme(self, house, candidates, rng, purpose):
        """A seeded weighted draw among the three highest utilities (ties by
        schemes.csv row order, then target), weighted by utility."""
        ranked = sorted(candidates, key=lambda c: (-c[0], c[1], c[2], c[3]))
        top = [c for c in ranked if c[0] > 0][: self.rules.scheme_rules["choice"]["top"]]
        if not top:
            return None
        key = rng.weighted([(self._candidate_key(c), c[0]) for c in top], purpose=purpose)
        return next(c for c in top if self._candidate_key(c) == key)

    def _turns_remaining(self, scheme):
        if scheme["status"] != "active":
            return 0
        return scheme["steps_total"] - scheme["steps_done"] + 1

    def _scheme_event(self, scheme_id, phase, season, line=True, extra=None):
        """Every begin, step, answer, abandonment and resolution is an event
        with its turns remaining; a step and a resolution write no line."""
        s = self._scheme(scheme_id)
        spec = self._scheme_spec(s["scheme"])
        house = s["house"]
        peerage = self.house_row(house)["peerage"]
        target = s["target_house"]
        target_peerage = self.house_row(target)["peerage"] if target else ""
        riding = self._riding_name(s["target_riding"]) if s["target_riding"] else None
        payload = {
            "id": scheme_id,
            "name": s["scheme"],
            "phase": phase,
            "turns_remaining": self._turns_remaining(s),
            "committed": s["committed_capital"] + s["committed_influence"],
        }
        if target:
            payload["target_house"] = target
        if riding is not None:
            payload["riding"] = riding
        if s["answers"] is not None:
            payload["answers"] = s["answers"]
        if extra:
            payload.update(extra)
        text = None
        if line:
            template = spec.begins if phase in ("begun", "answered") else spec.abandons
            text = f"Season {season} · " + (
                template.replace("{house}", peerage)
                .replace("{target}", target_peerage)
                .replace("{riding}", riding or "")
            )
        return self.record(
            "other",
            f"{peerage}: {s['scheme']} ({phase})",
            [house] + ([target] if target else []),
            season,
            band=self.band_for(self.personal_year(house)),
            line=text,
            delta={"scheme": payload},
        )

    def _scheme_step(self, scheme_id, season, phase="step"):
        s = self._scheme(scheme_id)
        spec = self._scheme_spec(s["scheme"])
        capital, influence = self._step_cost(s["house"], spec, s["target_house"])
        self.set_stats(s["house"], capital=-capital, influence=-influence)
        self.conn.execute(
            "UPDATE schemes SET steps_done = steps_done + 1,"
            " committed_capital = committed_capital + ?,"
            " committed_influence = committed_influence + ? WHERE id = ?",
            (capital, influence, scheme_id),
        )
        self._scheme_event(scheme_id, phase, season, line=phase != "step")

    def _begin_scheme(self, house, spec, target_house, target_riding, season, rng,
                      answers=None, steps=None):
        if steps is None:
            steps = spec.steps_min if spec.steps_min == spec.steps_max else rng.randint(
                spec.steps_min, spec.steps_max, f"scheme.steps.{house}"
            )
        cursor = self.conn.execute(
            "INSERT INTO schemes (house, scheme, target_house, target_riding, answers,"
            " steps_total, begun_season) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (house, spec.scheme, target_house, target_riding, answers, steps, season),
        )
        phase = "answered" if answers is not None else "begun"
        self._scheme_step(cursor.lastrowid, season, phase=phase)
        outcome = {"action": spec.scheme, "success": True, "scheme": phase}
        if target_house:
            outcome["with"] = target_house
        if target_riding:
            outcome["riding"] = self._riding_name(target_riding)
        return outcome

    def _end_scheme(self, scheme_id, status, outcome, season):
        self.conn.execute(
            "UPDATE schemes SET status = ?, outcome = ?, ended_season = ? WHERE id = ?",
            (status, outcome, season, scheme_id),
        )

    def _abandon_scheme(self, scheme_id, season, reason):
        """Abandon a scheme, returning abandon_refund_pct of what it holds, and
        with it any answer begun against it."""
        s = self._scheme(scheme_id)
        pct = self.rules.scheme_rules["choice"]["abandon_refund_pct"]
        self.set_stats(
            s["house"],
            capital=s["committed_capital"] * pct // 100,
            influence=s["committed_influence"] * pct // 100,
        )
        self._end_scheme(scheme_id, "abandoned", reason, season)
        self._scheme_event(scheme_id, "abandoned", season, extra={"reason": reason})
        for answer in self.conn.execute(
            "SELECT id, scheme FROM schemes WHERE answers = ? AND status = 'active' ORDER BY id",
            (scheme_id,),
        ).fetchall():
            if answer["scheme"] not in self._contest_schemes():
                self._abandon_scheme(answer["id"], season, "the claim is withdrawn")

    def _close_scheme(self, scheme_id, outcome, season):
        """A scheme reaching its resolution: recorded, ledger-only, with how
        many turns it ran."""
        s = self._scheme(scheme_id)
        self._end_scheme(scheme_id, "resolved", outcome, season)
        self._scheme_event(
            scheme_id, "resolved", season, line=False,
            extra={"outcome": outcome, "ran": season - s["begun_season"] + 1},
        )

    def _end_schemes_of(self, house, season):
        """A house leaving play ends its schemes; the removal is their event."""
        if not self.feature("schemes"):
            return
        self.conn.execute(
            "UPDATE schemes SET status = 'abandoned', outcome = 'house gone', ended_season = ?"
            " WHERE house = ? AND status = 'active'",
            (season, house),
        )

    def _abort_reason(self, s, season):
        """Why a scheme can no longer go on, or None."""
        spec = self._scheme_spec(s["scheme"])
        house, target, fed_id = s["house"], s["target_house"], s["target_riding"]
        if target is not None and self.house_row(target)["status"] != "active":
            return "target gone"
        kind = spec.resolves_as
        if kind == "contest":
            if mechanics._holder_of(self.conn, fed_id) != target \
                    or (target, fed_id) not in self._claim_targets(house):
                return "target gone"
            if self.relation_marker(house, target) in (KIN, COMPACT):
                return "bound by alliance"
            if self._contest_cooldown(house, target, season):
                return "the field is decided"
        elif kind == "frontier":
            if mechanics._holder_of(self.conn, fed_id) is not None:
                return "target gone"
            if not self.riding_open(fed_id, self.personal_year(house)):
                return "target closed"
        elif kind == "Purchase riding":
            if target not in self._purchase_targets(house):
                return "target recovered"
        elif kind == "Dispute":
            if target not in self._dispute_candidates(house, season):
                return "quarrel ended"
        elif kind == "Marriage alliance":
            if target not in self._match_candidates(house):
                return "no match"
        elif kind == "Petition elevation":
            if self.rank_index.get(self.house_row(house)["rank"], 0) >= self.rank_index["Marquis"] \
                    or self.holding_count(house) < 3:
                return "out of reach"
        elif kind == "Propose compact":
            if self.relation_marker(house, target) != FRIENDLY:
                return "relation changed"
        elif kind == "Name heir":
            if not self._can_name_heir(house):
                return "line secured"
        elif kind == "Reconcile":
            if self.relation_marker(house, target) not in (GRIEVANCE, HOSTILE):
                return "quarrel ended"
        elif kind in ("fortify", "sue"):
            claim = self._scheme(s["answers"])
            if claim is None or claim["status"] != "active":
                return "claim over"
        if s["steps_done"] < s["steps_total"] and not self._affords(house, spec, target):
            return "funds gone"
        return None

    def _reconsider_scheme(self, house, season):
        """A succession re-evaluates the house's scheme under the new holder."""
        if not self.feature("schemes"):
            return
        s = self.active_scheme(house)
        if s is None:
            return
        spec = self._scheme_spec(s["scheme"])
        value = self.scheme_utility(house, spec, s["target_house"], s["target_riding"], season)
        if value < self.rules.scheme_rules["choice"]["abandon_below"]:
            self._abandon_scheme(s["id"], season, "the new holder")

    def _scheme_turn(self, house, season, rng):
        """Rules 1.0 `schemes`: a house's turn in place of the action draw."""
        current = self.active_scheme(house)
        if current is not None:
            reason = self._abort_reason(current, season)
            if reason is not None:
                self._abandon_scheme(current["id"], season, reason)
                current = None

        pending = self.conn.execute(
            "SELECT * FROM schemes WHERE status = 'active' AND target_house = ?"
            " AND considered = 0 ORDER BY id",
            (house,),
        ).fetchall()
        pending = [p for p in pending if p["scheme"] in self._contest_schemes()]
        if pending:
            claim = pending[0]
            for p in pending:
                self.conn.execute("UPDATE schemes SET considered = 1 WHERE id = ?", (p["id"],))
            if current is None or current["answers"] != claim["id"]:
                candidates = self._scheme_candidates(house, season, claim=claim)
                stand = self.rules.scheme_rules["choice"]["answer_stand"]
                candidates.append((stand, len(self.rules.schemes), "", "", None))
                chosen = self._choose_scheme(house, candidates, rng, f"scheme.answer.{house}")
                if chosen is not None and chosen[4] is not None:
                    self.conn.execute(
                        "UPDATE schemes SET considered = 2 WHERE id = ?", (claim["id"],)
                    )
                    if current is not None:
                        self._abandon_scheme(current["id"], season, "set aside")
                    spec = chosen[4]
                    steps = None
                    if spec.resolves_as == "fortify":
                        steps = max(1, self._turns_remaining(claim))
                    return self._begin_scheme(
                        house, spec, chosen[2] or None, chosen[3] or None, season, rng,
                        answers=claim["id"], steps=steps,
                    )

        if current is not None:
            return self._advance_scheme(current, season, rng)

        chosen = self._choose_scheme(
            house, self._scheme_candidates(house, season), rng, f"scheme.choose.{house}"
        )
        if chosen is None:
            return {"action": "Bide", "success": True, "note": "no scheme"}
        return self._begin_scheme(house, chosen[4], chosen[2] or None, chosen[3] or None, season, rng)

    def _advance_scheme(self, s, season, rng):
        spec = self._scheme_spec(s["scheme"])
        if s["steps_done"] < s["steps_total"]:
            self._scheme_step(s["id"], season)
            outcome = {"action": spec.scheme, "success": True, "scheme": "step"}
            if s["target_house"]:
                outcome["with"] = s["target_house"]
            return outcome
        if spec.resolves_as == "fortify":
            return {"action": spec.scheme, "success": True, "scheme": "holds",
                    "with": s["target_house"]}
        return self._resolve_scheme(s, season, rng)

    def _resolve_with(self, house, name, season, rng, bonus):
        """resolve_action with a bonus from what the scheme committed."""
        action = self.actions[name]
        row = self.house_row(house)
        band = self.band_for(self.personal_year(house))
        if action.target == "auto":
            success, roll = True, None
        else:
            roll = rng.two_d6(purpose=f"resolve.{name}.{house}")
            modifier = int(action.enclosure_bonus.lstrip("+") or 0) \
                if row["enclosed"] and action.enclosure_bonus else 0
            success = roll + modifier + bonus >= action.target
        handler = getattr(self, f"_do_{_slug(name)}")
        return handler(house, season, rng, success, band, roll)

    def _resolve_scheme(self, s, season, rng):
        spec = self._scheme_spec(s["scheme"])
        kind = spec.resolves_as
        per = self.rules.scheme_rules["contest"]["committed_per_point"]
        bonus = (s["committed_capital"] + s["committed_influence"]) // per
        if kind == "contest":
            outcome = self._contest(s, season, rng)
            self._close_scheme(s["id"], outcome["contest"], season)
        elif kind == "frontier":
            outcome = self._frontier(s, season, rng, bonus)
            self._close_scheme(s["id"], "success" if outcome["success"] else "failure", season)
        elif kind == "sue":
            outcome = self._sue(s, season, rng, bonus)
            self._close_scheme(s["id"], "success" if outcome["success"] else "failure", season)
        else:
            self._scheme_target = s["target_house"]
            try:
                outcome = self._resolve_with(s["house"], kind, season, rng, bonus)
            finally:
                self._scheme_target = None
            self._close_scheme(s["id"], "success" if outcome.get("success") else "failure", season)
        outcome["scheme"] = "resolved"
        outcome["plan"] = spec.scheme
        return outcome

    def _settle(self, house, fed_id, season, band, roll, scheme_id):
        """Take an unclaimed riding: the record Expand writes, at Expand's cost."""
        row = self.house_row(house)
        name = self._riding_name(fed_id)
        year = self.personal_year(house)
        delta = {"riding": name, "roll": roll, "scheme": scheme_id}
        jurisdiction = (
            self.jurisdiction_name(fed_id, year) if self.feature("atlas_jurisdiction") else None
        )
        if jurisdiction is not None:
            delta["jurisdiction"] = jurisdiction
        event_id = self.record(
            "expansion",
            f"{row['peerage']} takes {name}",
            [house],
            season,
            band=band,
            line=f"Season {season} · {row['peerage']} takes {name}"
                 f"{self._jurisdiction_suffix(fed_id, year)}.",
            delta=delta,
        )
        self.conn.execute(
            "INSERT INTO holdings (house, fed_id, seat_order, hex, acquired_event_id)"
            " VALUES (?, ?, ?, ?, ?)",
            (house, fed_id, mechanics._next_seat_order(self.conn, house),
             mechanics._expansion_hex(self.conn, house), event_id),
        )
        self.set_stats(house, capital=-(15 + self.wealth_offset(fed_id)))
        return name

    def _land_neighbours(self, fed_id):
        return [
            row["fed_id"] for row in self.conn.execute(
                "SELECT CASE WHEN fed_id_a = ? THEN fed_id_b ELSE fed_id_a END AS fed_id"
                " FROM adjacency WHERE adjacency_type = 'land' AND (fed_id_a = ? OR fed_id_b = ?)"
                " ORDER BY fed_id",
                (fed_id, fed_id, fed_id),
            )
        ]

    def _frontier(self, s, season, rng, bonus):
        """Open the frontier: Expand on the named riding; a roll at or above
        frontier.double_on takes a second open riding beside it."""
        house, fed_id = s["house"], s["target_riding"]
        band = self.band_for(self.personal_year(house))
        roll = rng.two_d6(purpose=f"resolve.Expand.{house}")
        name = self._riding_name(fed_id)
        if roll + bonus < self.actions["Expand"].target:
            return {"action": "Expand", "success": False, "riding": name}
        self._settle(house, fed_id, season, band, roll, s["id"])
        outcome = {"action": "Expand", "success": True, "riding": name}
        if roll >= self.rules.scheme_rules["frontier"]["double_on"]:
            year = self.personal_year(house)
            beside = [
                n for n in self._land_neighbours(fed_id)
                if mechanics._holder_of(self.conn, n) is None and self.riding_open(n, year)
            ]
            if beside:
                second = rng.choice(beside, purpose=f"frontier.second.{house}")
                if self.house_row(house)["capital"] >= 15 + self.wealth_offset(second):
                    outcome["second"] = self._settle(house, second, season, band, roll, s["id"])
        return outcome

    def _call_allies(self, party, opponent, scheme_id, side, season, rng):
        """Houses bound to `party` by compact or kin, asked in name order; each
        joins on a per-cent utility test, and a refusal is recorded too."""
        spec = self.rules.scheme_rules["contest"]
        party_peerage = self.house_row(party)["peerage"]
        joined = []
        for ally in self.houses_related_by(party, {COMPACT, KIN}):
            if ally == opponent:
                continue
            value = spec["ally_accept"]
            if self.relation_marker(party, ally) == KIN:
                value += spec["ally_kin"]
            if self.relation_marker(ally, opponent) in (COMPACT, KIN):
                value += spec["ally_bound_both"]
            if self.feature("prestige_politics"):
                leader, _ = self._ranking()
                if party == leader:
                    value += self.rules.scheme_rules["utility"]["leader_ally"]
            joins = rng.chance(clamp(value, 0, 100), purpose=f"contest.ally.{ally}")
            ally_peerage = self.house_row(ally)["peerage"]
            line = (
                f"Season {season} · {ally_peerage} stands with {party_peerage}"
                f" against {self.house_row(opponent)['peerage']}."
                if joins else
                f"Season {season} · {ally_peerage} declines to stand with {party_peerage}."
            )
            self.record(
                "other",
                f"{ally_peerage} {'joins' if joins else 'declines'} {party_peerage}",
                [ally, party, opponent],
                season,
                band=self.band_for(self.personal_year(ally)),
                line=line,
                delta={"ally": {"scheme": scheme_id, "side": side, "party": party, "joins": joins}},
            )
            if joins:
                joined.append(ally)
        return joined

    def _transfer(self, loser, winner, fed_id, event_id):
        """Move one riding between houses under an event; the loser's seats
        renumber, so a lost seat passes to its next riding (hard rule 4)."""
        self.conn.execute(
            "UPDATE holdings SET released_event_id = ? WHERE house = ? AND fed_id = ?"
            " AND released_event_id IS NULL",
            (event_id, loser, fed_id),
        )
        self.conn.execute(
            "INSERT INTO holdings (house, fed_id, seat_order, hex, acquired_event_id)"
            " VALUES (?, ?, ?, ?, ?)",
            (winner, fed_id, mechanics._next_seat_order(self.conn, winner),
             mechanics._expansion_hex(self.conn, winner), event_id),
        )
        self._renumber(loser)

    def _fall(self, house, by, season, band):
        """A house with no ridings left falls, naming the house that took its seat."""
        row = self.house_row(house)
        self.record(
            "succession",
            f"{row['peerage']} falls",
            [house, by],
            season,
            band=band,
            line=f"Season {season} · {row['peerage']} falls; "
                 f"{self.house_row(by)['peerage']} has taken its seat.",
            delta={"nature": "extinction", "reason": "fell", "taken_by": by},
        )
        self.conn.execute("UPDATE houses SET status = 'removed' WHERE house = ?", (house,))
        self.conn.execute(
            "UPDATE house_stats SET removed_season = ? WHERE house = ?", (season, house)
        )
        self.conn.execute(
            "UPDATE persons SET alive = 0, died_season = ? WHERE house = ? AND alive = 1",
            (season, house),
        )
        self._end_schemes_of(house, season)

    def contest_totals(self, attacker, defender, fed_id, committed, fortified, allies_a, allies_d,
                       roll_a, roll_d):
        """Rules 1.0 `contested_claims` (§4.4): the two totals of a contest."""
        spec = self.rules.scheme_rules["contest"]
        a_row, d_row = self.house_row(attacker), self.house_row(defender)
        attack = (
            roll_a + committed // spec["committed_per_point"]
            + self.rank_index.get(a_row["rank"], 0) + spec["per_ally"] * allies_a
            + self._trait_effect(attacker, "claim")
        )
        defence = (
            roll_d + fortified // spec["fortified_per_point"]
            + d_row["cohesion"] // spec["cohesion_per_point"] + spec["per_ally"] * allies_d
            + (spec["seat_bonus"] if self._is_seat(defender, fed_id) else 0)
        )
        return attack, defence

    def _contest(self, s, season, rng):
        """Resolve a claim. Higher total wins, ties to the defender; the loser
        loses what it committed and loss_cohesion; a win by rout_margin over
        a house below rout_cohesion_below takes a second riding; a house left
        with no riding falls; the pair is hostile and may not contest again
        for the cooldown."""
        spec = self.rules.scheme_rules["contest"]
        attacker, defender, fed_id = s["house"], s["target_house"], s["target_riding"]
        a_row, d_row = self.house_row(attacker), self.house_row(defender)
        band = self.band_for(self.personal_year(attacker))
        name = self._riding_name(fed_id)
        allies_a = self._call_allies(attacker, defender, s["id"], "attacker", season, rng)
        allies_d = self._call_allies(defender, attacker, s["id"], "defender", season, rng)
        fort = self.conn.execute(
            "SELECT * FROM schemes WHERE answers = ? AND status = 'active' AND scheme = 'Fortify'"
            " ORDER BY id LIMIT 1",
            (s["id"],),
        ).fetchone()
        fortified = 0 if fort is None else fort["committed_capital"] + fort["committed_influence"]
        roll_a = rng.two_d6(purpose=f"contest.attack.{attacker}")
        roll_d = rng.two_d6(purpose=f"contest.defend.{defender}")
        attack, defence = self.contest_totals(
            attacker, defender, fed_id, s["committed_capital"] + s["committed_influence"],
            fortified, len(allies_a), len(allies_d), roll_a, roll_d,
        )
        cohesion_before = d_row["cohesion"]
        totals = {"attacker": attack, "defender": defence}
        if attack > defence:
            event_id = self.record(
                "challenge",
                f"{a_row['peerage']} takes {name} from {d_row['peerage']}",
                [attacker, defender],
                season,
                band=band,
                line=f"Season {season} · {a_row['peerage']} wins its claim to {name}"
                     f" against {d_row['peerage']}, {attack} to {defence}.",
                delta={"contest": "won", "scheme": s["id"], "riding": name, **totals},
            )
            self._transfer(defender, attacker, fed_id, event_id)
            self.set_stats(defender, cohesion=-spec["loss_cohesion"])
            self._tally(attacker, won=1)
            self._tally(defender, lost=1)
            self._turn_cache = {}
            if attack - defence >= spec["rout_margin"] and cohesion_before < spec["rout_cohesion_below"]:
                second = self._adjacent_holding_of(attacker, defender)
                if second is not None:
                    second_name = self._riding_name(second)
                    rout_id = self.record(
                        "challenge",
                        f"{a_row['peerage']} takes {second_name} from {d_row['peerage']}",
                        [attacker, defender],
                        season,
                        band=band,
                        line=f"Season {season} · {a_row['peerage']} drives on and takes"
                             f" {second_name} from {d_row['peerage']}.",
                        delta={"contest": "rout", "scheme": s["id"], "riding": second_name},
                    )
                    self._transfer(defender, attacker, second, rout_id)
                    self._tally(defender, lost=1)
                    self._turn_cache = {}
            result = "won"
        else:
            event_id = self.record(
                "challenge",
                f"{d_row['peerage']} holds {name} against {a_row['peerage']}",
                [attacker, defender],
                season,
                band=band,
                line=f"Season {season} · {d_row['peerage']} holds {name} against"
                     f" {a_row['peerage']}'s claim, {defence} to {attack}.",
                delta={"contest": "held", "scheme": s["id"], "riding": name, **totals},
            )
            self.set_stats(attacker, cohesion=-spec["loss_cohesion"])
            self._tally(defender, won=1)
            result = "held"
        self.set_relation(attacker, defender, HOSTILE, event_id, f"contest over {name}")
        self._sync(attacker, defender, event_id, season)
        if fort is not None:
            self._close_scheme(fort["id"], "lost" if result == "won" else "held", season)
        if result == "won" and self.holding_count(defender) == 0:
            self._fall(defender, attacker, season, band)
        return {"action": s["scheme"], "success": result == "won", "with": defender,
                "riding": name, "contest": result}

    def _sue(self, s, season, rng, bonus):
        """Sue for peace: the weaker side cedes the claimed riding, unless it
        is its seat; otherwise the house buys peace at the indemnity, on
        Reconcile's roll. Either way the claim ends."""
        house, other = s["house"], s["target_house"]
        claim = self._scheme(s["answers"])
        row, other_row = self.house_row(house), self.house_row(other)
        band = self.band_for(self.personal_year(house))
        fed_id = claim["target_riding"]
        if (
            self.standing(house) < self.standing(other)
            and mechanics._holder_of(self.conn, fed_id) == house
            and not self._is_seat(house, fed_id)
        ):
            name = self._riding_name(fed_id)
            event_id = self.record(
                "transfer",
                f"{row['peerage']} cedes {name} to {other_row['peerage']}",
                [house, other],
                season,
                band=band,
                line=f"Season {season} · {row['peerage']} cedes {name} to"
                     f" {other_row['peerage']} to end its claim.",
                delta={"reason": "cession", "riding": name, "under_claim": claim["id"],
                       "scheme": claim["id"]},
            )
            self._transfer(house, other, fed_id, event_id)
            self._tally(house, lost=1)
            self.set_relation(house, other, RESOLVED, event_id, "cession under a claim")
            self._sync(house, other, event_id, season)
            self._close_scheme(claim["id"], "ceded", season)
            return {"action": "Cede / swap", "success": True, "with": other, "riding": name}
        roll = rng.two_d6(purpose=f"resolve.Reconcile.{house}")
        if roll + bonus < self.actions["Reconcile"].target:
            return {"action": "Reconcile", "success": False, "with": other}
        indemnity = min(row["capital"], self.rules.scheme_rules["peace"]["indemnity_capital"])
        self.set_stats(house, capital=-indemnity)
        self.set_stats(other, capital=indemnity)
        event_id = self.record(
            "relational",
            f"{row['peerage']} buys peace from {other_row['peerage']}",
            [house, other],
            season,
            band=band,
            line=f"Season {season} · {row['peerage']} buys peace from {other_row['peerage']}.",
            delta={"marker": RESOLVED, "peace": claim["id"], "indemnity": indemnity,
                   "scheme": claim["id"]},
        )
        self.set_relation(house, other, RESOLVED, event_id, "peace bought")
        self._sync(house, other, event_id, season)
        self._close_scheme(claim["id"], "peace", season)
        return {"action": "Reconcile", "success": True, "with": other}

    def _plans(self):
        """Every public scheme at the end of a season, for the record."""
        return [
            {
                "id": s["id"],
                "house": s["house"],
                "scheme": s["scheme"],
                "target_house": s["target_house"],
                "riding": self._riding_name(s["target_riding"]) if s["target_riding"] else None,
                "turns_remaining": self._turns_remaining(s),
                "begun": s["begun_season"],
                "committed": s["committed_capital"] + s["committed_influence"],
            }
            for s in self.conn.execute(
                "SELECT * FROM schemes WHERE status = 'active' ORDER BY id"
            ).fetchall()
        ]


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
            # Rules 1.0 `holder_traits`: each Zealot holder on an opposed-tag
            # border adds its friction effect.
            delta += self._trait_effect(row_a["house"], "friction")
            delta += self._trait_effect(row_b["house"], "friction")
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

        if row["capital"] >= 40 and not row["enclosed"] and self.can_expand_into_open(house):
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

        # Rules 1.0 `marriage_pairing`: legal only when a man and a woman can be
        # paired from the two houses' unmarried heirs and children.
        if self.feature("marriage_pairing"):
            legal.discard("Marriage alliance")
            if any(self._marriage_pair(house, other) for other in friendly):
                legal.add("Marriage alliance")
        # Rules 1.0 `upkeep_phase`: upkeep does what these four did.
        if self.feature("upkeep_phase"):
            legal -= UPKEEP_ACTIONS

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
        holder_trait_rows = self._holder_trait_rows(house)

        bonus_for = defaultdict(int)
        for objective in held:
            spec = self.objectives.get(objective)
            if spec is None:
                continue
            for action in spec.action_weight_bonus:
                bonus_for[action] += 2 * WEIGHT_SCALE

        # Every weight below is an integer at WEIGHT_SCALE: the design's "+2" is
        # 2*WEIGHT_SCALE, and Dispute's "+ambition/2" is ambition*(WEIGHT_SCALE//2),
        # which is exact rather than a float that happens to look like one.
        # The list is built in sorted action order, and the draw walks it in that
        # order, so the cumulative scan is fully determined by this file.
        weights = []
        for name in sorted(legal):
            action = self.actions[name]
            try:
                weight = int(action.base_weight) * WEIGHT_SCALE
            except ValueError:
                continue  # 'forced' actions are never drawn from the pool

            if name == "Expand":
                weight += row["ambition"] * WEIGHT_SCALE
                if row["cohesion"] < 40:
                    weight -= 2 * WEIGHT_SCALE
            elif name == "Invest" and row["capital"] < 40:
                weight += 2 * WEIGHT_SCALE
            elif name == "Consolidate (rest)" and row["cohesion"] < 40:
                weight += 3 * WEIGHT_SCALE
            elif name == "Name heir" and holder is not None and holder["age"] > 60:
                weight += ((holder["age"] - 60) // 5) * WEIGHT_SCALE
            elif name == "Dispute":
                weight += row["ambition"] * (WEIGHT_SCALE // 2)
                if row["cohesion"] < 50:
                    weight -= 3 * WEIGHT_SCALE
            elif name == "Reconcile" and row["cohesion"] < 40:
                weight += 2 * WEIGHT_SCALE
            elif name == "Correspond":
                same_tag = [
                    other for other in self.houses_within_reach(house)
                    if self.house_row(other)["tag"] == row["tag"]
                ]
                if same_tag:
                    weight += 2 * WEIGHT_SCALE
                if self.houses_related_by(house, {GRIEVANCE}):
                    weight -= 2 * WEIGHT_SCALE

            weight += bonus_for.get(name, 0)
            # Rules 1.0 `holder_traits`: each of the holder's traits shifts the
            # actions it names, in units of WEIGHT_SCALE.
            for trait in holder_trait_rows:
                weight += trait.actions.get(name, 0) * WEIGHT_SCALE
            if row["enclosed"] and name in ENCLOSURE_DOUBLED:
                weight *= 2
            weights.append((name, max(0, weight)))
        return weights

    def take_action(self, house, season, rng):
        # A director's forced action (§12) pre-empts the draw for one season and
        # is cleared as it is taken. It bypasses the weights but not the rules:
        # an action the house cannot legally take is still refused, and the house
        # falls back to its ordinary draw rather than doing nothing.
        forced = self.house_row(house)["forced_action"]
        if forced:
            self.conn.execute(
                "UPDATE house_stats SET forced_action = NULL WHERE house = ?", (house,)
            )
            if forced in self.legal_actions(house):
                rng.draw(f"action.{house}", {"forced_by": "director", "action": forced})
                outcome = self.resolve_action(house, forced, season, rng)
                if outcome is not None:
                    outcome["forced"] = True
                return outcome
            rng.draw(
                f"action.{house}",
                {"forced_by": "director", "action": forced, "refused": "not legal this season"},
            )

        # Rules 1.0 `schemes`: the weighted draw is not used.
        if self.feature("schemes"):
            return self._scheme_turn(house, season, rng)

        legal = self.legal_actions(house)
        weights = self.action_weights(house, legal)
        name = rng.weighted(weights, purpose=f"action.{house}")
        if name is None:
            # Rules 1.0 `upkeep_phase`: with the four standing actions gone, a
            # house can have nothing legal to do; the record says it bides.
            if self.feature("upkeep_phase"):
                return {"action": "Bide", "success": True, "note": "no legal action"}
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

        targets = self.open_expansion_targets(house)
        if not targets:
            return {"action": "Expand", "success": False, "note": "no target"}
        fed_id = rng.choice(targets, purpose=f"expand.target.{house}")
        name = self._riding_name(fed_id)
        year = self.personal_year(house)

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
            self._tally(rival["house"], lost=1)
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

        expansion_delta = {"riding": name, "roll": roll}
        jurisdiction = (
            self.jurisdiction_name(fed_id, year) if self.feature("atlas_jurisdiction") else None
        )
        if jurisdiction is not None:
            expansion_delta["jurisdiction"] = jurisdiction
        event_id = self.record(
            "expansion",
            f"{row['peerage']} takes {name}",
            [house],
            season,
            band=band,
            line=f"Season {season} · {row['peerage']} takes {name}"
                 f"{self._jurisdiction_suffix(fed_id, year)}.",
            delta=expansion_delta,
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
        # Rules 0.9 `riding_endowments`: 15 + (wealth_tier - 3) of the target.
        self.set_stats(house, capital=-(15 + self.wealth_offset(fed_id)))
        outcome = {"action": "Expand", "success": True, "riding": name}
        if jurisdiction is not None:
            outcome["jurisdiction"] = jurisdiction
        return outcome

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
        cursor = self.conn.execute(
            "INSERT INTO persons (house, name, gender, age, role, alive, born_season)"
            " VALUES (?, ?, ?, ?, ?, 1, ?)",
            (house, f"{given} {surname}", gender, heir_age, role, season),
        )
        # Rules 1.0 `holder_traits`: an heir's traits are drawn, and public,
        # when the heir is named.
        heir_traits = self._give_traits(cursor.lastrowid, house, rng)
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
            delta=self._with_traits({"heir_age": heir_age, "role": role}, heir_traits),
        )
        # Rules 1.0 `succession_watch`: an heir named already of age has come of age.
        if role == "heir" and self.feature("succession_watch") \
                and heir_age >= self.rules.succession["watch"]["heir_of_age"]:
            self._record_of_age(house, f"{given} {surname}", heir_age, season, band)
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
        # Rules 1.0 `schemes`: a scheme names its target; nothing is drawn.
        if self._scheme_target is not None:
            return self._scheme_target if self._scheme_target in options else None
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
                delta=self._letter_delta({"marker": GRIEVANCE, "cause": "correspondence"}),
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
            delta=self._letter_delta({"marker": marker}),
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
        # Rules 1.0 `schemes`: Make peace may end open hostility as well.
        quarrels = {GRIEVANCE, HOSTILE} if self.feature("schemes") else {GRIEVANCE}
        other = self._pick(
            rng, self.houses_related_by(house, quarrels), f"reconcile.target.{house}"
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
        hardens = self.rules.friction["dispute_outcome"]["hardens_probability_pct"]
        if self._scheme_target is not None:
            # Rules 1.0 `schemes`: Break a rival hardens on success.
            marker = HOSTILE
        else:
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
        self._tally(house, won=1)
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
        self._tally(house, won=1)
        self._tally(other, lost=1)
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
        self._tally(other, lost=1)
        self._sync(house, other, event_id, season)
        return {"action": "Purchase riding", "success": True, "with": other, "riding": name}

    def _do_marriage_alliance(self, house, season, rng, success, band, roll):
        row = self.house_row(house)
        pairing = self.feature("marriage_pairing")
        candidates = [
            other for other in self.houses_related_by(house, {FRIENDLY, COMPACT})
            if (self._marriage_pair(house, other) if pairing else self._unmarried_heir(other))
        ]
        other = self._pick(rng, candidates, f"marriage.target.{house}")
        if other is None or not success or (not pairing and not self._unmarried_heir(house)):
            return {"action": "Marriage alliance", "success": False}

        other_row = self.house_row(other)
        if pairing:
            mine, theirs = self._marriage_pair(house, other)
        else:
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
        self._end_schemes_of(other, season)
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
            weights = [
                (
                    o.objective,
                    WEIGHT_SCALE
                    + 2 * WEIGHT_SCALE * self._objective_favoured(o.objective, row, house),
                )
                for o in self.rules.objectives
                if o.objective not in held
            ]
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
        return LoggingRandom(prng.Prng(season_seed(self.world_seed, season_no)), self.log)

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

        prestige = self._compute_prestige(1) if self.feature("prestige") else None
        record = self._write_season(1, [], house, prestige=prestige)
        record["kind"] = "initial"
        record["seat"] = seat
        self._rewrite_season_file(1, record)
        return record

    def _write_season_file(self, season, record):
        """Write one season log, and return the repo-relative path recorded in
        the seasons row. A world with no seasons_dir writes nothing and records
        NULL — the database still holds the season, only the log is skipped.

        The bytes are canonical (Phase 10-1): `canonical_json` is what the
        JavaScript engine writes too, so `scripts/crosscheck.py` can compare the
        two engines' seasons with a plain byte comparison instead of a
        structural diff that would have to decide for itself which differences
        matter.
        """
        if self.seasons_dir is None:
            return None
        self.seasons_dir.mkdir(parents=True, exist_ok=True)
        path = self.seasons_dir / f"{season:04d}.json"
        path.write_text(canonical_json(record), encoding="utf-8")

        # What gets recorded is the season's home in the *record*, not wherever
        # this particular run happened to write it. The referee replays into a
        # scratch directory before it publishes, and recording the write path put
        # /tmp/hoc-referee-xxxx/0001.json into the published database as the
        # season's home — a temp path, in the canonical state, naming a
        # directory that no longer exists.
        try:
            canonical = scenario.seasons_dir() / f"{season:04d}.json"
        except Exception:
            canonical = path
        for candidate in (canonical, path):
            try:
                return str(candidate.relative_to(scenario.REPO_ROOT))
            except ValueError:
                continue
        return str(path)

    def _rewrite_season_file(self, season, record):
        """Re-write a season log after adding fields the writer did not know."""
        self._write_season_file(season, record)

    def run_season(self, season_no=None):
        """Play one season, in §6's order. Returns the season's log record."""
        season = season_no if season_no is not None else self.season_no + 1
        self.log = []
        self.chronicle = []
        self._noticed = set()
        rng = self.rng_for(season)

        # 1. Clocks and ages.
        if "clocks" in self.phases:
            self._age_everyone(season)

        # Borders warm or cool before anyone acts, so a grievance struck this
        # season is available to the houses that act after it (rules 0.6).
        self._turn_cache = {}
        if "friction" in self.phases:
            self._run_friction(season, rng)

        outcomes = []
        self._expansion_claims = {}
        for row in self.active_houses():
            house = row["house"]
            self._turn_cache = {}
            if self.house_row(house)["removed_season"] is not None:
                continue

            # Rules 1.0: upkeep before anything else in the turn, then the
            # succession watch.
            if self.feature("upkeep_phase"):
                self._upkeep(house)
            if self.feature("cohesion_strain"):
                self._strain(house)
            if self.feature("succession_watch"):
                self._succession_watch(house, season)

            # 2. Era events, which may demand an extra mortality roll.
            fired = self._era_event(house, season, rng) if "events" in self.phases else None
            extra_mortality = bool(fired and fired["extra_mortality"])

            # 3. Mortality and succession.
            if "mortality" in self.phases:
                if self._mortality(house, season, rng, extra_roll=extra_mortality):
                    continue

            # 4-5. Action selection and resolution.
            if "actions" in self.phases:
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
                # Rules 1.0 `upkeep_phase`: one automatic letter a turn.
                if self.feature("upkeep_phase"):
                    self._letter(house, season, rng)

            # 6. Objectives, then the §7c debt check.
            if "objectives" in self.phases:
                self._check_objectives(house, season, rng)
            if "debt" in self.phases:
                self._debt_check(house, season, rng)

        # 7. Founding roll.
        founded = self._founding_roll(season, rng) if "founding" in self.phases else None

        # 8. Enclosure recompute.
        if "enclosure" in self.phases:
            self._recompute_enclosure(season)

        # 9. Rules 0.8: say something when nothing happened.
        if self.feature("quiet_season_line"):
            self._quiet_season_lines(season)

        # Rules 1.0 `prestige`: every active house's, once the season is done.
        prestige = self._compute_prestige(season) if self.feature("prestige") else None

        # 10. The season record.
        # Rules 1.0 `schemes`: every public scheme, as the season left them.
        plans = self._plans() if self.feature("schemes") else None
        return self._write_season(season, outcomes, founded, prestige=prestige, plans=plans)

    # A house that has done nothing worth recording for this many consecutive
    # seasons is noticed once. Ten is long enough that it is a fact about the
    # house rather than about the dice: a house acts every season, so ten
    # seasons of silence means ten actions that all failed or all rested.
    QUIET_HOUSE_SEASONS = 10

    def _quiet_season_lines(self, season):
        """§0.8: the two lines that fire when nothing else did.

        Order matters and is fixed in both engines: the season's own line first,
        decided against the chronicle as the season's phases left it, then the
        idle-house lines in active-house order. Deciding the season line after
        the house lines would mean a silent season with one idle house never got
        one, which is backwards — that season is quieter, not louder.
        """
        if not self.chronicle:
            self.chronicle.append(f"Season {season} · A quiet year across the peerage.")

        for row in self.active_houses():
            house = row["house"]
            if house in self._noticed:
                self.conn.execute(
                    "UPDATE house_stats SET quiet_seasons = 0 WHERE house = ?", (house,)
                )
                continue
            quiet = (row["quiet_seasons"] or 0) + 1
            self.conn.execute(
                "UPDATE house_stats SET quiet_seasons = ? WHERE house = ?", (quiet, house)
            )
            # Exactly at the threshold, so a house that stays quiet for fifty
            # seasons is mentioned once rather than forty-one times.
            if quiet == self.QUIET_HOUSE_SEASONS:
                held = self.holdings(house)
                if held:
                    self.chronicle.append(
                        f"Season {season} · {row['peerage']} keeps to {held[0]['name_en']}."
                    )

    def _founding_roll(self, season, rng):
        """§10: high on an empty map, falling smoothly to zero as land runs out.

        The coefficient and exponent come from rules/founding.json, not from
        here — tuning the founding rate is a rules change with a CHANGELOG entry,
        never a code change (§11).
        """
        if self.feature("founding_curve"):
            return self._founding_curve_roll(season, rng)
        spec = self.rules.founding["p_found"]
        room = self.founding_room()
        # The only floating-point computation in the engine, and the only float
        # comparison: sqrt(room / 343) * coefficient, against rand_float().
        # IEEE-754 makes division, multiplication and sqrt exact-or-correctly-
        # rounded, so Python and JavaScript compute the same double here; a
        # general pow would not be safe (docs/DETERMINISM.md, hoc/prng.py).
        p_found = prng.p_found(room, TOTAL_RIDINGS, spec["coefficient"])
        rng.draw("founding.p_found", {"room": room, "p": p_found})
        if p_found <= 0:
            return None
        if not rng.chance_float(p_found, purpose="founding.roll"):
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

    def _interventions_since(self, season):
        """Director interventions applied between the last season and this one.

        They arrive as turn files, outside the season loop, so the season record
        would otherwise have no trace of them — and a season log that cannot
        explain why a house did something unaccountable is not an audit trail.
        """
        previous = self.conn.execute(
            "SELECT MAX(season_no) AS n FROM seasons WHERE season_no < ?", (season,)
        ).fetchone()["n"]
        # Interventions arrive through the turn runner, which stamps its events
        # source='turn'; what marks one as a director's intervention is the
        # after_season key that only the §12 operations write.
        rows = self.conn.execute(
            "SELECT title, mechanical_delta FROM events"
            " WHERE mechanical_delta LIKE '%after_season%' ORDER BY id"
        ).fetchall()

        # The turn runner merges each operation's delta under its own key and
        # keeps a list per key, so an intervention's after_season sits one level
        # down rather than at the top of the event's delta.
        out = []
        for row in rows:
            try:
                delta = json.loads(row["mechanical_delta"] or "{}")
            except ValueError:
                continue
            for operation, entries in delta.items():
                for entry in entries if isinstance(entries, list) else [entries]:
                    if not isinstance(entry, dict):
                        continue
                    after = entry.get("after_season")
                    if after is None or after >= season:
                        continue
                    if previous is not None and after < previous:
                        continue
                    out.append({"operation": operation, "title": row["title"], **entry})
        return out

    def _write_season(self, season, outcomes, founded, prestige=None, plans=None):
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
            "rules_version": self.rules_version,
            # Which engine wrote this file. Excluded from the cross-check
            # comparison by scripts/crosscheck.py — it is the one field the two
            # engines are expected to disagree about, and the only one.
            "engine": {"impl": "python", "rules_version": self.rules_version},
            "interventions": self._interventions_since(season),
            "draws": self.log,
            "actions": outcomes,
            "founded": founded,
            "chronicle": self.chronicle,
            "houses_after": houses_after,
            "ridings_after": ridings_after,
        }
        if prestige is not None:
            record["prestige"] = prestige
        if plans is not None:
            record["plans"] = plans

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
                self.rules_version,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        return record

    def run(self, count, stop_on=()):
        """Play `count` seasons, stopping early on any named condition."""
        unknown = set(stop_on) - STOP_CONDITIONS
        if unknown:
            raise SimError(
                f"unknown stop condition(s) {', '.join(sorted(unknown))};"
                f" valid conditions are {', '.join(sorted(STOP_CONDITIONS))}"
            )

        records = []
        for _ in range(count):
            record = self.run_season()
            records.append(record)
            hit = self._stop_conditions(record) & set(stop_on)
            if hit:
                record["stopped_on"] = sorted(hit)
                break
        return records

    def run_summary(self, records, before):
        """A machine-readable account of a run, for the engine workflow to parse.

        `before` is the (houses, ridings) count taken before the first season, so
        the summary can say what the run changed rather than only where it ended.
        """
        last = records[-1] if records else None
        chronicle = [line for record in records for line in record["chronicle"]]
        return {
            "seasons_run": len(records),
            "season_from": records[0]["season"] if records else self.season_no,
            "season_to": last["season"] if last else self.season_no,
            "stopped_on": (last or {}).get("stopped_on", []),
            "stopped_at_season": last["season"] if last and last.get("stopped_on") else None,
            "houses_before": before[0],
            "houses_after": last["houses_after"] if last else before[0],
            "ridings_before": before[1],
            "ridings_after": last["ridings_after"] if last else before[1],
            "chronicle": chronicle[-SUMMARY_CHRONICLE_LINES:],
            "chronicle_total": len(chronicle),
            "rules_version": self.rules_version,
            "seed": self.world_seed,
        }

    def counts(self):
        """(active houses, ridings held) right now."""
        row = self.conn.execute(
            "SELECT (SELECT COUNT(*) FROM houses WHERE status = 'active') AS houses,"
            " (SELECT COUNT(*) FROM holdings WHERE released_event_id IS NULL) AS ridings"
        ).fetchone()
        return row["houses"], row["ridings"]

    def _stop_conditions(self, record):
        """Which of §12's pause conditions this season met.

        `removal` is any house leaving play — extinction or absorption alike,
        since from the director's chair both are a house gone from the map.
        `extinction` and `partition` are the narrower conditions, so a director
        watching for cadet lines is not woken by every absorbed neighbour.
        """
        hit = set()
        season = record["season"]
        rows = self.conn.execute(
            "SELECT e.kind, e.title, e.mechanical_delta FROM events e"
            " WHERE e.source = 'engine' ORDER BY e.id DESC LIMIT 400"
        ).fetchall()
        for row in rows:
            try:
                delta = json.loads(row["mechanical_delta"] or "{}")
            except ValueError:
                continue
            if delta.get("season") != season:
                continue
            nature = delta.get("nature")
            if nature in ("extinction", "absorption"):
                hit.add("removal")
            if nature == "extinction":
                hit.add("extinction")
            if nature == "partition":
                hit.add("partition")
            if row["kind"] == "challenge":
                hit.add("challenge")
            if delta.get("magnitude") == "Major":
                hit.add("major")
            if delta.get("to") in ("Marquis", "Marchioness"):
                hit.add("marquis")
        return hit

    # ---------------------------------------------------------------- replay --

    @classmethod
    def replay(cls, conn, paths, seasons_dir=None, world=None):
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

        # A caller replaying season by season (to interleave interventions)
        # passes the world back in so its cached rules and seed are reused.
        if world is None:
            world = cls(
                conn, world_seed=first["seed"], seasons_dir=seasons_dir,
                rules_version=first.get("rules_version"),
            )
        for path in paths:
            with open(path, encoding="utf-8") as f:
                record = json.load(f)
            # Each season is replayed under the rules it was played under. A
            # record spanning a version change — which every long game
            # eventually does — switches here, and reloading is cheap enough
            # beside a season that it is not worth caching across the boundary.
            world.use_rules_version(record.get("rules_version"))
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
