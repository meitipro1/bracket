# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
Cutline — the best K of N, and an honest answer when the line is arbitrary
=========================================================================

WHAT IT IS
    Select the best K of N against a written criterion. Consensus is on SET
    MEMBERSHIP only.

WHY THIS IS DELIBERATELY LOOSER THAN SLATE
    For a grant round, a shortlist, or a payout tier, one question matters: who
    got in. Whether the third and fourth entrant were in that order is not a
    fact anyone acts on, and demanding agreement about it would reject
    perfectly correct work for no benefit.

    So Cutline throws away more than Slate does, on purpose. It is the same
    lever pulled harder.

        what crosses consensus   "0|3|7"   who is in, not who is first

THE BOUNDARY PROBLEM, AND THE DESIGN DECISION
    If item K and item K+1 are indistinguishable, the cut is arbitrary. The
    network will agree on a selection, but the selection it agrees on is noise
    dressed as a decision -- which is worse than failing, because it looks
    authoritative.

    So Cutline bands the scores exactly as Slate does, then inspects the
    boundary. What happens next is DECLARED AT REGISTRATION:

        refuse   store the attempt, mark it cut_is_arbitrary, select nobody.
                 Correct when K is a hard budget.
        expand   include the whole tied band, so the selection may exceed K.
                 Correct when K is a target and fairness matters more than the
                 exact count.

    Neither is right in general, which is precisely why it is a parameter
    rather than a hardcoded policy. A contract that silently picked one would be
    making a governance decision on the caller's behalf.

WHY THIS IS NOT A THIN LLM WRAPPER
    The model scores. It never decides who is in. The band boundaries, the cut,
    and the tie policy are all pure functions against values frozen on chain
    before the model ran.

    Cutline calls Tiebreak's question internally: is this difference real, or is
    it noise? Here it decides whether the cut falls inside a tie.
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

REFUSE = "refuse"
EXPAND = "expand"
ON_TIE = (REFUSE, EXPAND)

ARBITRARY = "cut_is_arbitrary"

CRITERION_MIN = 12
CRITERION_MAX = 300
ITEM_MAX = 600
REASON_MAX = 300
MIN_ITEMS = 2
MAX_ITEMS = 12


def parse_scores(text, n):
    """Pipe-joined text to floats. None on anything unusable."""
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


def is_permutation(order, n):
    """Reject anything that is not exactly 0..n-1, once each."""
    if len(order) != n:
        return False
    seen = []
    for i in order:
        if i < 0 or i >= n or i in seen:
            return False
        seen.append(i)
    return True


def parse_order(text, n):
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


def parse_closeness(text):
    try:
        v = float(str(text))
    except (TypeError, ValueError):
        return None
    if v != v or v == INF or v == -INF or v < 0:
        return None
    return v


def band_scores(scores, closeness):
    """Adjacent scores within `closeness` share a band. Transitive along the run."""
    bands = []
    current = 1
    for i in range(len(scores)):
        if i > 0 and abs(scores[i - 1] - scores[i]) > closeness:
            current += 1
        bands.append(current)
    return bands


def cut_at(bands, k, on_tie):
    """Where the line falls, and whether it fell inside a tie.

    Returns (selected_count, arbitrary) given banded scores in rank order.
    """
    if k <= 0:
        return 0, False
    if k >= len(bands):
        return len(bands), False
    if bands[k - 1] != bands[k]:
        return k, False           # clean boundary between two bands
    if on_tie == REFUSE:
        return 0, True
    n = k                          # expand through the whole tied band
    while n < len(bands) and bands[n] == bands[k - 1]:
        n += 1
    return n, False


def canonical_selection(selected):
    """Sorted indices. Membership without order."""
    return "|".join(str(i) for i in sorted(selected))


def select_from(order, bands, k, on_tie):
    """The selected item indices, and whether the cut was arbitrary."""
    count, arbitrary = cut_at(bands, k, on_tie)
    return [order[i] for i in range(count)], arbitrary


def canonicalise(order_text, scores_text, n, closeness, k, on_tie):
    """Everything the deterministic half does, in one place.

    Returns (canonical, arbitrary) with canonical None when unusable. The
    leader's payload and the validator's own run go down this identical path,
    which is what makes the agreement rule symmetric.
    """
    order = parse_order(order_text, n)
    if order is None:
        return None, False
    scores = parse_scores(scores_text, n)
    if scores is None:
        return None, False
    bands = band_scores(scores, closeness)
    selected, arbitrary = select_from(order, bands, k, on_tie)
    return canonical_selection(selected), arbitrary


def cutline_agrees(mine, theirs, n, closeness, k, on_tie):
    """Consensus on the sorted selected indices, and on the refusal flag.

    The refusal is part of the agreement on purpose: two nodes that select the
    same nobody, one because the cut was arbitrary and one because K was zero,
    have not agreed about anything worth recording.
    """
    a, a_arb = canonicalise(mine.get("order", ""), mine.get("scores", ""),
                            n, closeness, k, on_tie)
    b, b_arb = canonicalise(theirs.get("order", ""), theirs.get("scores", ""),
                            n, closeness, k, on_tie)
    if a is None or b is None:
        return False
    return a == b and a_arb == b_arb


def split_items(text):
    out = []
    for part in str(text).split("|"):
        s = " ".join(part.split())
        if s != "":
            out.append(s)
    return out


def sanitise_reason(raw, cap=REASON_MAX):
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
    return "|".join(str(int(v)) for v in values)


def join_scores(values):
    return "|".join(repr(float(v)) for v in values)


# --- PURE RULES END ---------------------------------------------------------


@allow_storage
@dataclass
class Item:
    cutline_id: u256
    idx: u256
    text: str


@allow_storage
@dataclass
class Pick:
    selection_id: u256
    item_idx: u256


@allow_storage
@dataclass
class Selection:
    cutline_id: u256
    canonical: str
    refusal: str
    why: str
    at: str


@allow_storage
@dataclass
class Cutline:
    author: Address
    criterion: str
    closeness: str
    on_tie: str
    k: u256
    n_items: u256


class Contract(gl.Contract):
    cutlines: DynArray[Cutline]
    items: DynArray[Item]
    selections: DynArray[Selection]
    picks: DynArray[Pick]

    def __init__(self):
        pass

    # -- writes -------------------------------------------------------------

    @gl.public.write
    def define(self, criterion: str, items: str, k: u256,
               closeness: str, on_tie: str) -> None:
        """Freeze the criterion, the items, K, the threshold and the tie policy."""
        c = " ".join(str(criterion).split())
        if len(c) < CRITERION_MIN or len(c) > CRITERION_MAX:
            raise gl.vm.UserError("criterion must be 12 to 300 characters")

        parts = split_items(items)
        if len(parts) < MIN_ITEMS or len(parts) > MAX_ITEMS:
            raise gl.vm.UserError("a cutline holds 2 to 12 items")
        for p in parts:
            if len(p) > ITEM_MAX:
                raise gl.vm.UserError("an item may be at most 600 characters")
        if len(set(parts)) != len(parts):
            raise gl.vm.UserError("items must be distinct")

        kk = int(k)
        if kk < 1 or kk >= len(parts):
            raise gl.vm.UserError("k must be at least 1 and fewer than the items")
        if parse_closeness(closeness) is None:
            raise gl.vm.UserError("closeness must be a finite number, zero or more")

        policy = str(on_tie).strip().lower()
        if policy not in ON_TIE:
            raise gl.vm.UserError("on_tie must be refuse or expand")

        cutline_id = len(self.cutlines)
        self.cutlines.append(
            Cutline(
                author=gl.message.sender_address,
                criterion=c,
                closeness=str(closeness).strip(),
                on_tie=policy,
                k=u256(kk),
                n_items=u256(len(parts)),
            )
        )
        for i in range(len(parts)):
            self.items.append(
                Item(cutline_id=u256(cutline_id), idx=u256(i), text=parts[i])
            )

    @gl.public.write
    def select(self, cutline_id: u256) -> None:
        """Score, band, cut, agree, store."""
        cl = self._cutline(cutline_id)

        criterion = str(cl.criterion)
        n = int(cl.n_items)
        k = int(cl.k)
        on_tie = str(cl.on_tie)
        closeness = parse_closeness(cl.closeness)
        texts = self._item_texts(int(cutline_id))
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
            return cutline_agrees(leader_fn(), leaders_res.calldata,
                                  n, closeness, k, on_tie)

        res = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

        order = parse_order(res.get("order", ""), n)
        scores = parse_scores(res.get("scores", ""), n)
        if order is None:
            raise gl.vm.UserError("the returned order is not a permutation")
        if scores is None:
            raise gl.vm.UserError("the score count does not match the item count")

        bands = band_scores(scores, closeness)
        selected, arbitrary = select_from(order, bands, k, on_tie)
        canonical = canonical_selection(selected)

        selection_id = len(self.selections)
        self.selections.append(
            Selection(
                cutline_id=u256(int(cutline_id)),
                canonical=canonical,
                refusal=ARBITRARY if arbitrary else "",
                why=sanitise_reason(res.get("why", "")),
                at=str(gl.message_raw["datetime"]),
            )
        )
        for idx in sorted(selected):
            self.picks.append(
                Pick(selection_id=u256(selection_id), item_idx=u256(idx))
            )

    # -- views --------------------------------------------------------------

    @gl.public.view
    def count(self) -> u256:
        return u256(len(self.cutlines))

    @gl.public.view
    def selected(self, cutline_id: u256) -> str:
        """Sorted indices, or "" when the cut was refused or nothing ran.

        Empty rather than raising, so a consuming contract has one branch to
        handle instead of two.
        """
        self._cutline(cutline_id)
        sid = self._last_selection(int(cutline_id))
        if sid < 0:
            return ""
        return str(self.selections[sid].canonical)

    @gl.public.view
    def latest(self, cutline_id: u256) -> dict:
        cl = self._cutline(cutline_id)
        sid = self._last_selection(int(cutline_id))
        texts = self._item_texts(int(cutline_id))
        if sid < 0:
            return {
                "selected": False,
                "criterion": str(cl.criterion),
                "k": int(cl.k),
                "on_tie": str(cl.on_tie),
                "canonical": "",
                "cut_is_arbitrary": False,
                "picks": [],
                "why": "",
                "reason_is_leader_supplied": True,
                "at": "",
            }
        s = self.selections[sid]
        rows = []
        for j in range(len(self.picks)):
            p = self.picks[j]
            if int(p.selection_id) != sid:
                continue
            idx = int(p.item_idx)
            rows.append(
                {"item_idx": idx, "item": texts[idx] if idx < len(texts) else ""}
            )
        return {
            "selected": True,
            "criterion": str(cl.criterion),
            "k": int(cl.k),
            "on_tie": str(cl.on_tie),
            "canonical": str(s.canonical),
            # True means the cut fell inside a tied band and the policy was
            # refuse: nobody was selected, on purpose.
            "cut_is_arbitrary": str(s.refusal) == ARBITRARY,
            "picks": rows,
            "why": str(s.why),
            "reason_is_leader_supplied": True,
            "at": str(s.at),
        }

    # -- internals ----------------------------------------------------------

    def _cutline(self, cutline_id: u256):
        i = int(cutline_id)
        if i < 0 or i >= len(self.cutlines):
            raise gl.vm.UserError("no such cutline")
        return self.cutlines[i]

    def _item_texts(self, cutline_id: int):
        out = []
        for j in range(len(self.items)):
            it = self.items[j]
            if int(it.cutline_id) == cutline_id:
                out.append(str(it.text))
        return out

    def _last_selection(self, cutline_id: int) -> int:
        """The index of the most recent selection for this parent, or -1.

        An INDEX, deliberately, never the object. A storage object is a
        view on a slot rather than a copy, and indexing the array builds a
        fresh view every time, so `self.selections[i] is obj` is always False on a
        node. Carrying the index instead is the only thing that survives.
        """
        for j in range(len(self.selections) - 1, -1, -1):
            s = self.selections[j]
            if int(s.cutline_id) == cutline_id:
                return j
        return -1
