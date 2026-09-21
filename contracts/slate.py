# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
Slate — an ordering, with the ties left in
==========================================

WHAT IT IS
    Order N items against a written criterion, collapsing items that cannot be
    told apart into a shared rank.

    The output is not a list. It is a BANDED ordering: rank 1, rank 2, rank 2,
    rank 4. Two items sharing rank 2 is the contract saying it will not pretend
    to separate them.

HOW CONSENSUS IS USED  (the decision the whole contract turns on)
    What does NOT work: comparing the raw ordering with strict_eq. Two honest
    validators asked to rank eight proposals will swap two adjacent near-equal
    items roughly every time, and the contract never settles.

    What ALSO does not work: loosening to a prompt-based principle and asking a
    model whether two orderings "mean the same thing". That accepts an ordering
    that reversed the top two, which is the only part anyone cares about.

    WHAT WORKS: the block returns an ordering and a score per item. The contract
    then bands those scores deterministically, in Python, using a closeness
    threshold frozen at registration, and consensus compares the banded rank
    vector canonicalised to a single string.

        block returns   order  = "2|0|1|3"          item indices, best first
                        scores = "88.0|71.5|70.9|40.0"
        contract makes  "2:1|0:2|1:2|3:3"           items 0 and 1 tie at rank 2

    Cheap, brutal, and correct, because the noise was removed BEFORE the
    comparison rather than tolerated during it.

THE MOVE BEING DEMONSTRATED
    Canonicalise, then use the cheapest principle. Most contracts reach for a
    looser equivalence principle when strict equality fails. The better instinct
    is to ask what noise is causing the failure, remove it deterministically,
    and keep strict equality.

WHY THIS IS NOT A THIN LLM WRAPPER
    The model proposes an order and a score per item. It never decides the
    ranking. The bands, and therefore the ranks, come from a pure function
    against a threshold frozen on chain before the model ran. A worse model
    produces more ties, which is the correct response to a worse model.

    Slate calls Tiebreak's question internally: is this difference real, or is
    it noise? Here it decides which items share a rank.
"""

from genlayer import *
from dataclasses import dataclass


# --- PURE RULES BEGIN -------------------------------------------------------

INF = float("inf")

MARKUP = "<>{}`[]\\"

#: Error classification. Only one class can occur inside the block here: these
#: contracts make no web request, so there is no external 4xx to distinguish
#: from a transient 5xx, and every business-logic refusal happens in the
#: DETERMINISTIC half where it surfaces to the caller as a plain UserError.
#: What is left is a model that answered with something that is not an object at
#: all, and the correct response to that is to disagree and force rotation --
#: agreeing on broken model output would lock bad state.
ERROR_LLM = "[LLM_ERROR]"

UNDIFFERENTIATED = "undifferentiated"

CRITERION_MIN = 12
CRITERION_MAX = 300
ITEM_MAX = 600
REASON_MAX = 300
MIN_ITEMS = 2
MAX_ITEMS = 12


def parse_scores(text, n):
    """Pipe-joined text to floats. None on anything unusable.

    Non-finite is a failure, never a value. "1e400" overflows straight to
    infinity, and infinity is within `closeness` of nothing and everything
    depending on which side you stand on, so an infinity that reached banding
    would make the bands depend on arithmetic nobody intended.
    """
    if n <= 0:
        return None
    parts = str(text).split("|")
    if len(parts) != n:
        return None
    out = []
    for p in parts:
        try:
            v = float(p)
        except (TypeError, ValueError):
            return None
        if v != v or v == INF or v == -INF:
            return None
        out.append(v)
    return out


def parse_order(text, n):
    """Pipe-joined indices to a permutation of 0..n-1, or None."""
    parts = str(text).split("|")
    if len(parts) != n:
        return None
    out = []
    for p in parts:
        s = p.strip()
        if s == "" or not s.isdigit():
            return None
        out.append(int(s))
    if not is_permutation(out, n):
        return None
    return out


def is_permutation(order, n):
    """Reject anything that is not exactly 0..n-1, once each.

    A model that repeats an index has dropped an item, and a ranking that
    silently omits an item is worse than no ranking, because it looks complete.
    """
    if len(order) != n:
        return False
    seen = []
    for i in order:
        if i < 0 or i >= n or i in seen:
            return False
        seen.append(i)
    return True


def parse_closeness(text):
    """The banding threshold, stored and read as text. None if unusable."""
    try:
        v = float(str(text))
    except (TypeError, ValueError):
        return None
    if v != v or v == INF or v == -INF or v < 0:
        return None
    return v


def band_scores(scores, closeness):
    """Adjacent scores within `closeness` share a band.

    Banding is TRANSITIVE along the sorted run, deliberately: if a is close to b
    and b is close to c, all three share a band even when a and c are further
    apart than the threshold. The alternative is a banding that depends on which
    pair you compare first, which is not deterministic in any useful sense and
    so cannot be the thing consensus rests on.

    `scores` arrives in rank order, best first.
    """
    bands = []
    current = 1
    for i in range(len(scores)):
        if i > 0 and abs(scores[i - 1] - scores[i]) > closeness:
            current += 1
        bands.append(current)
    return bands


def canonical_order(order, bands):
    """The string that crosses consensus, and nothing else does.

    Item indices are sorted WITHIN each band. This is the whole point of the
    exercise: two honest validators asked to rank eight proposals will swap two
    adjacent near-equal items roughly every time, and if that swap changed the
    canonical string the contract would never settle -- which is exactly the
    failure banding exists to remove. Between bands the order is meaningful and
    is preserved; inside a band the contract has already said it will not
    pretend to separate them, so the order there carries no information and must
    not carry any weight either.
    """
    out = []
    i = 0
    while i < len(order):
        j = i
        while j < len(order) and bands[j] == bands[i]:
            j += 1
        for idx in sorted(order[i:j]):
            out.append(str(idx) + ":" + str(bands[i]))
        i = j
    return "|".join(out)


def canonicalise(order_text, scores_text, n, closeness):
    """Everything the deterministic half does to a block result, in one place.

    Returns the canonical string, or "" when the result is unusable. Both the
    leader's payload and the validator's own run go through this identical
    path, which is what makes the agreement rule symmetric.
    """
    order = parse_order(order_text, n)
    if order is None:
        return ""
    scores = parse_scores(scores_text, n)
    if scores is None:
        return ""
    return canonical_order(order, band_scores(scores, closeness))


def slate_agrees(mine, theirs, n, closeness):
    """Consensus is on the banded rank vector, and on nothing else.

    Symmetric by construction: both sides go down the same canonicalise() path
    and the result is compared with equality. An unusable payload canonicalises
    to "" and is never agreed with, on either side.
    """
    a = canonicalise(mine.get("order", ""), mine.get("scores", ""), n, closeness)
    b = canonicalise(theirs.get("order", ""), theirs.get("scores", ""), n, closeness)
    if a == "" or b == "":
        return False
    return a == b


def is_undifferentiated(bands):
    """Every item in one band: the criterion does not discriminate at all.

    Not a broken run. A finding. Store it, expose it, and let the caller decide
    whether to rewrite the criterion.
    """
    if len(bands) == 0:
        return False
    for b in bands:
        if b != bands[0]:
            return False
    return True


def split_items(text):
    """Pipe-joined items to a list, whitespace collapsed, empties dropped."""
    out = []
    for part in str(text).split("|"):
        s = " ".join(part.split())
        if s != "":
            out.append(s)
    return out


def sanitise_reason(raw, cap=REASON_MAX):
    """Strip markup and control characters from leader-supplied prose."""
    out = []
    for ch in str(raw):
        if ch in MARKUP:
            continue
        if ord(ch) < 32 or ord(ch) == 127:
            out.append(" ")
        else:
            out.append(ch)
    return " ".join("".join(out).split())[:cap]


def build_prompt(criterion, items_block, n):
    """One template. The items are numbered so the model returns indices."""
    return (
        "You are ranking " + str(n) + " items against one criterion.\n"
        "\n"
        "Criterion: " + criterion + "\n"
        "\n"
        "Items, by index:\n"
        + items_block + "\n"
        "\n"
        "Rank every item, best first, and score each out of 100.\n"
        "Use every index exactly once.\n"
        "Reply with JSON: {\"order\": [indices, best first], "
        "\"scores\": [score for each index in that same order], "
        "\"why\": \"one short sentence\"}\n"
    )


def join_ints(values):
    """A list of numbers as the pipe-joined text the boundary carries."""
    return "|".join(str(int(v)) for v in values)


def join_scores(values):
    """Scores as text, so no float formatting difference can become a mismatch."""
    return "|".join(repr(float(v)) for v in values)


# --- PURE RULES END ---------------------------------------------------------


@allow_storage
@dataclass
class Item:
    slate_id: u256
    idx: u256
    text: str


@allow_storage
@dataclass
class Placement:
    ranking_id: u256
    item_idx: u256
    rank: u256
    band: u256


@allow_storage
@dataclass
class Ranking:
    slate_id: u256
    canonical: str
    refusal: str
    why: str
    at: str


@allow_storage
@dataclass
class Slate:
    author: Address
    criterion: str
    closeness: str
    n_items: u256


class Contract(gl.Contract):
    slates: DynArray[Slate]
    items: DynArray[Item]
    rankings: DynArray[Ranking]
    placements: DynArray[Placement]

    def __init__(self):
        pass

    # -- writes -------------------------------------------------------------

    @gl.public.write
    def define(self, criterion: str, items: str, closeness: str) -> None:
        """Freeze the criterion, the items and the banding threshold.

        `items` is a single pipe-joined string, not list[str]. A list parameter
        is close enough to a documented GenVM restriction to be a bet rather
        than a decision, and this family does not take that bet.
        """
        c = " ".join(str(criterion).split())
        if len(c) < CRITERION_MIN or len(c) > CRITERION_MAX:
            raise gl.vm.UserError("criterion must be 12 to 300 characters")

        parts = split_items(items)
        if len(parts) < MIN_ITEMS or len(parts) > MAX_ITEMS:
            raise gl.vm.UserError("a slate holds 2 to 12 items")
        for p in parts:
            if len(p) > ITEM_MAX:
                raise gl.vm.UserError("an item may be at most 600 characters")
        if len(set(parts)) != len(parts):
            raise gl.vm.UserError("items must be distinct")

        if parse_closeness(closeness) is None:
            raise gl.vm.UserError("closeness must be a finite number, zero or more")

        slate_id = len(self.slates)
        self.slates.append(
            Slate(
                author=gl.message.sender_address,
                criterion=c,
                closeness=str(closeness).strip(),
                n_items=u256(len(parts)),
            )
        )
        for i in range(len(parts)):
            self.items.append(
                Item(slate_id=u256(slate_id), idx=u256(i), text=parts[i])
            )

    @gl.public.write
    def rank(self, slate_id: u256) -> None:
        """Order, band, agree, store."""
        s = self._slate(slate_id)

        # Plain values only. A block cannot read storage at all.
        criterion = str(s.criterion)
        n = int(s.n_items)
        closeness = parse_closeness(s.closeness)
        texts = self._item_texts(int(slate_id))
        items_block = "\n".join(str(i) + ". " + texts[i] for i in range(n))

        def leader_fn():
            out = gl.nondet.exec_prompt(
                build_prompt(criterion, items_block, n), response_format="json"
            )
            if not isinstance(out, dict):
                raise gl.vm.UserError(
                    ERROR_LLM + " prompt returned " + type(out).__name__
                )
            order = out.get("order", [])
            scores = out.get("scores", [])
            # Flat dict of str. A list here would fail inside the calldata
            # encoder, outside the contract, with Result Code <unknown> and no
            # traceback at all.
            return {
                "order": join_ints(order) if isinstance(order, list) else str(order),
                "scores": join_scores(scores) if isinstance(scores, list) else str(scores),
                "why": sanitise_reason(out.get("why", "")),
            }

        def validator_fn(leaders_res):
            # A leader that did not return is a leader whose model misbehaved --
            # the only error class reachable inside this block. Disagree, which
            # forces rotation; agreeing on broken model output would lock it in.
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            return slate_agrees(leader_fn(), leaders_res.calldata, n, closeness)

        res = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

        # Re-derived on this side too. The block proposes; the deterministic
        # half decides.
        order = parse_order(res.get("order", ""), n)
        scores = parse_scores(res.get("scores", ""), n)
        if order is None:
            raise gl.vm.UserError("the returned order is not a permutation")
        if scores is None:
            raise gl.vm.UserError("the score count does not match the item count")

        bands = band_scores(scores, closeness)
        canonical = canonical_order(order, bands)
        refusal = UNDIFFERENTIATED if is_undifferentiated(bands) else ""

        ranking_id = len(self.rankings)
        self.rankings.append(
            Ranking(
                slate_id=u256(int(slate_id)),
                canonical=canonical,
                refusal=refusal,
                why=sanitise_reason(res.get("why", "")),
                at=str(gl.message_raw["datetime"]),
            )
        )
        for pos in range(n):
            self.placements.append(
                Placement(
                    ranking_id=u256(ranking_id),
                    item_idx=u256(order[pos]),
                    rank=u256(pos + 1),
                    band=u256(bands[pos]),
                )
            )

    # -- views --------------------------------------------------------------

    @gl.public.view
    def count(self) -> u256:
        return u256(len(self.slates))

    @gl.public.view
    def order(self, slate_id: u256) -> str:
        """The canonical banded ordering, or "" before any ranking."""
        self._slate(slate_id)
        rid = self._last_ranking(int(slate_id))
        if rid < 0:
            return ""
        return str(self.rankings[rid].canonical)

    @gl.public.view
    def slate(self, slate_id: u256) -> dict:
        s = self._slate(slate_id)
        return {
            "criterion": str(s.criterion),
            "closeness": str(s.closeness),
            "n_items": int(s.n_items),
            "items": self._item_texts(int(slate_id)),
            "author": str(s.author),
        }

    @gl.public.view
    def latest(self, slate_id: u256) -> dict:
        s = self._slate(slate_id)
        rid = self._last_ranking(int(slate_id))
        if rid < 0:
            return {
                "ranked": False,
                "criterion": str(s.criterion),
                "canonical": "",
                "refusal": "",
                "placements": [],
                "why": "",
                "reason_is_leader_supplied": True,
                "at": "",
            }
        r = self.rankings[rid]
        texts = self._item_texts(int(slate_id))
        rows = []
        for k in range(len(self.placements)):
            p = self.placements[k]
            if int(p.ranking_id) != rid:
                continue
            idx = int(p.item_idx)
            rows.append(
                {
                    "item_idx": idx,
                    "item": texts[idx] if idx < len(texts) else "",
                    "rank": int(p.rank),
                    "band": int(p.band),
                }
            )
        return {
            "ranked": True,
            "criterion": str(s.criterion),
            "canonical": str(r.canonical),
            # "undifferentiated" means every item landed in one band: the
            # criterion does not discriminate at all. A finding, not a fault.
            "refusal": str(r.refusal),
            "placements": rows,
            "why": str(r.why),
            "reason_is_leader_supplied": True,
            "at": str(r.at),
        }

    # -- internals ----------------------------------------------------------

    def _slate(self, slate_id: u256):
        """Bounds-checked lookup. A negative id would otherwise return the
        newest slate, correctly formatted, with nothing failing anywhere."""
        i = int(slate_id)
        if i < 0 or i >= len(self.slates):
            raise gl.vm.UserError("no such slate")
        return self.slates[i]

    def _item_texts(self, slate_id: int):
        out = []
        for k in range(len(self.items)):
            it = self.items[k]
            if int(it.slate_id) == slate_id:
                out.append(str(it.text))
        return out

    def _last_ranking(self, slate_id: int) -> int:
        """The index of the most recent ranking for this parent, or -1.

        An INDEX, deliberately, never the object. A storage object is a
        view on a slot rather than a copy, and indexing the array builds a
        fresh view every time, so `self.rankings[i] is obj` is always False on a
        node. Carrying the index instead is the only thing that survives.
        """
        for k in range(len(self.rankings) - 1, -1, -1):
            r = self.rankings[k]
            if int(r.slate_id) == slate_id:
                return k
        return -1
