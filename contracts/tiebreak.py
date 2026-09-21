# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
Tiebreak — is this difference real, or is it noise?
===================================================

WHAT IT IS
    Decide whether two items are distinguishable under a written criterion, or
    whether any ordering between them would be noise. Three outcomes: item A
    wins, item B wins, or the pair is TIED.

    TIED is not a failure. It is the network agreeing, precisely, that the
    criterion does not separate these two.

THE FAILURE IT CATCHES
    Position bias. Language models systematically favour whichever option
    appears first. Ask "which is better, A or B?" and a position-biased model
    says A. Ask "which is better, B or A?" and it says B. It has expressed a
    preference about presentation order, not about the items.

    VALIDATOR CONSENSUS DOES NOT CATCH THIS. Every validator builds the prompt
    from the same template, so every validator presents the items in the same
    order, so every validator inherits the same bias and they all agree. The
    network converges confidently on an artefact of the prompt.

HOW CONSENSUS IS USED
    gl.vm.run_nondet_unsafe. Two prompts run sequentially inside ONE block --
    sequential prompts are legal, nested non-deterministic blocks are not.

        forward round   A shown first, B second
        reverse round   B shown first, A second

    Each round answers a, b or neither. Only two of the nine combinations are
    position-independent: a-then-a, and b-then-b. Everything else is TIED,
    including the case where the model simply names whichever item it saw first
    in each round, which is position bias in its purest form and the exact
    thing this contract exists to name.

    The validator has two layers. Layer one is a free internal honesty check:
    combine_rounds() is pure, so a validator confirms that the leader's own two
    rounds actually produce the verdict it reported, before running a single
    prompt. Layer two compares ONLY the verdict, never the raw rounds, because
    two honest nodes may differ on one round and still land on the same verdict.

WHY THIS IS NOT A THIN LLM WRAPPER
    The model never decides. It produces two a/b/neither answers, and the
    verdict comes from a pure combination function in the deterministic half,
    recomputed from the stored rounds before anything is written. Swap in a
    worse model and the mechanism still works; it just returns TIED more often,
    which is the correct response to a worse model.

THE ATOM OF THE FAMILY
    Slate, Cutline and Winnow all ask this same question internally: is this
    difference real, or is it noise? Slate uses it to decide which items share
    a rank, Cutline to decide whether the cut falls inside a tie, Winnow to
    decide whether an item belongs in the uncertain middle.

RELATIONSHIP TO CROSSCHECK
    Crosscheck asks one yes/no question twice in opposite framings and refuses
    when the framings disagree. Tiebreak applies that same insight to a
    different axis: instead of varying the framing of a question about one item,
    it varies the ORDER of two items. Naming the borrowed idea is stronger than
    hoping nobody notices.
"""

from genlayer import *
from dataclasses import dataclass


# --- PURE RULES BEGIN -------------------------------------------------------
#
# Everything between these markers is deterministic, dependency free, and read
# directly by tests/test_logic.py out of this file. There is no second copy to
# drift: a change here is a change to what the tests run.

A = "a"
B = "b"
NEITHER = "neither"
TIED = "tied"

VERDICTS = (A, B, TIED)

MARKUP = "<>{}`[]\\"

#: Error classification. Only one class can occur inside the block here: these
#: contracts make no web request, so there is no external 4xx to distinguish
#: from a transient 5xx, and every business-logic refusal happens in the
#: DETERMINISTIC half where it surfaces to the caller as a plain UserError.
#: What is left is a model that answered with something that is not an object at
#: all, and the correct response to that is to disagree and force rotation --
#: agreeing on broken model output would lock bad state.
ERROR_LLM = "[LLM_ERROR]"

CRITERION_MIN = 12
CRITERION_MAX = 300
ITEM_MAX = 600
REASON_MAX = 300


def normalise_side(raw):
    """Map whatever the model said onto exactly a, b or neither.

    Anything unrecognised becomes `neither`, which is the safe direction: an
    unreadable round can only ever produce TIED, never a winner. Mapping an
    unknown answer onto a side would let a malformed response decide a
    comparison.
    """
    s = str(raw).strip().lower()
    if s in (A, "item a", "a)", "first", "left"):
        return A
    if s in (B, "item b", "b)", "second", "right"):
        return B
    return NEITHER


def combine_rounds(forward, reverse):
    """Only a winner that survives BOTH presentation orders is real."""
    f = normalise_side(forward)
    r = normalise_side(reverse)
    if f == A and r == A:
        return A
    if f == B and r == B:
        return B
    return TIED


def tiebreak_agrees(mine, theirs):
    """Two layers, and the order of them is the point.

    LAYER 1 -- internal honesty, and it costs nothing. combine_rounds is pure,
    so a validator can confirm that a proposal's own two rounds produce the
    verdict it claims WITHOUT running any inference. A malformed or dishonest
    proposal dies before a single prompt is spent on it.

    LAYER 2 -- agreement on the verdict, never on the raw rounds. Two honest
    nodes may differ on one round and still land on the same verdict; forcing
    the rounds to match would reject correct work.

    Symmetric by construction: both sides go through the identical check, and
    the final comparison is an equality. agrees(x, y) == agrees(y, x).
    """
    for side in (mine, theirs):
        v = str(side.get("verdict", ""))
        if v not in VERDICTS:
            return False
        if combine_rounds(side.get("forward", ""), side.get("reverse", "")) != v:
            return False
    return str(mine.get("verdict", "")) == str(theirs.get("verdict", ""))


def sanitise_reason(raw, cap=REASON_MAX):
    """Strip markup and control characters from leader-supplied prose.

    The reasons are deliberately excluded from consensus: two honest readers
    describe the same shortfall differently, and comparing prose would stall
    every comparison. That means a leader picks them freely, so they are
    untrusted text on the way INTO storage. Nothing in this contract acts on
    them, and latest() says so.
    """
    out = []
    for ch in str(raw):
        if ch in MARKUP:
            continue
        if ord(ch) < 32 or ord(ch) == 127:
            out.append(" ")
        else:
            out.append(ch)
    return " ".join("".join(out).split())[:cap]


def build_prompt(criterion, first_label, first_text, second_label, second_text):
    """ONE template, one direction parameter. This is load-bearing.

    Both rounds must come from this single function. If the two prompts differed
    in tone, length or specificity, then a disagreement between them would
    measure the prompts rather than the model, and the primitive would mean
    nothing at all.

    The labels stay bound to the ITEMS, not to the positions: the model always
    answers about item a or item b, and only the order they appear in changes.
    That is what makes a changed answer evidence of position bias rather than of
    a relabelling.
    """
    return (
        "You are comparing two items against one criterion.\n"
        "\n"
        "Criterion: " + criterion + "\n"
        "\n"
        "Item " + first_label + ":\n"
        + first_text + "\n"
        "\n"
        "Item " + second_label + ":\n"
        + second_text + "\n"
        "\n"
        "Which item better meets the criterion?\n"
        "Answer \"neither\" if the criterion does not separate them.\n"
        "Reply with JSON: {\"winner\": \"a\" | \"b\" | \"neither\", "
        "\"why\": \"one short sentence\"}\n"
    )


def pct_text(part, whole):
    """A percentage as a canonical decimal string, one place.

    No float crosses the calldata boundary, so the string is built from integer
    arithmetic. A consuming contract gets the scaled integer beside it and can
    compare that; the string is for display only.
    """
    if whole <= 0:
        return "0.0"
    tenths = (part * 1000 + whole // 2) // whole
    return str(tenths // 10) + "." + str(tenths % 10)


def pct_scaled(part, whole):
    """The same percentage in tenths of a percent, as an integer."""
    if whole <= 0:
        return 0
    return (part * 1000 + whole // 2) // whole


# --- PURE RULES END ---------------------------------------------------------


@allow_storage
@dataclass
class Comparison:
    # Flat, and carrying its parent id, because a storage dataclass cannot hold
    # a collection. See DECISIONS.md.
    pair_id: u256
    verdict: str
    forward: str
    reverse: str
    why_forward: str
    why_reverse: str
    at: str


@allow_storage
@dataclass
class Pair:
    author: Address
    criterion: str
    item_a: str
    item_b: str
    n_a: u256
    n_b: u256
    n_tied: u256


class Contract(gl.Contract):
    # Every collection is a top level contract field. The runtime allocates
    # these; nothing has to be constructed in memory, which is the only shape
    # that reliably works.
    pairs: DynArray[Pair]
    comparisons: DynArray[Comparison]

    def __init__(self):
        pass

    # -- writes -------------------------------------------------------------

    @gl.public.write
    def register(self, criterion: str, item_a: str, item_b: str) -> None:
        """Freeze a pair and the criterion it will be judged against.

        Frozen at registration, not supplied at comparison time: letting a
        caller pass the criterion into compare() would let them keep rewording
        it until they got the answer they wanted.
        """
        c = " ".join(str(criterion).split())
        a = " ".join(str(item_a).split())
        b = " ".join(str(item_b).split())

        if len(c) < CRITERION_MIN or len(c) > CRITERION_MAX:
            raise gl.vm.UserError("criterion must be 12 to 300 characters")
        if a == "" or b == "":
            raise gl.vm.UserError("both items must be non-empty")
        if len(a) > ITEM_MAX or len(b) > ITEM_MAX:
            raise gl.vm.UserError("an item may be at most 600 characters")
        if a == b:
            raise gl.vm.UserError("the two items are identical")

        self.pairs.append(
            Pair(
                author=gl.message.sender_address,
                criterion=c,
                item_a=a,
                item_b=b,
                n_a=u256(0),
                n_b=u256(0),
                n_tied=u256(0),
            )
        )

    @gl.public.write
    def compare(self, pair_id: u256) -> None:
        """Both presentation orders, one block, one verdict."""
        p = self._pair(pair_id)

        # The block closes over plain strings only. It cannot read storage at
        # all, so everything it needs is extracted first.
        criterion = str(p.criterion)
        item_a = str(p.item_a)
        item_b = str(p.item_b)

        def leader_fn():
            forward_raw = gl.nondet.exec_prompt(
                build_prompt(criterion, A, item_a, B, item_b),
                response_format="json",
            )
            reverse_raw = gl.nondet.exec_prompt(
                build_prompt(criterion, B, item_b, A, item_a),
                response_format="json",
            )
            # Defensive before anything else. A model that answered with a
            # string, a list, or nothing at all has not answered, and calling
            # .get on it would surface as a raw contract error with a traceback
            # rather than as a rotation.
            for raw in (forward_raw, reverse_raw):
                if not isinstance(raw, dict):
                    raise gl.vm.UserError(
                        ERROR_LLM + " prompt returned " + type(raw).__name__
                    )
            f = normalise_side(forward_raw.get("winner", ""))
            r = normalise_side(reverse_raw.get("winner", ""))
            # Flat dict of str, and nothing else. A bool or a nested mapping
            # here fails inside the calldata encoder, outside the contract,
            # with Result Code <unknown> and no traceback at all.
            return {
                "forward": f,
                "reverse": r,
                "verdict": combine_rounds(f, r),
                "why_forward": sanitise_reason(forward_raw.get("why", "")),
                "why_reverse": sanitise_reason(reverse_raw.get("why", "")),
            }

        def validator_fn(leaders_res):
            # A leader that did not return is a leader whose model misbehaved --
            # the only error class reachable inside this block. Disagree, which
            # forces rotation; agreeing on broken model output would lock it in.
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            # Independent verification, not a schema check: the validator runs
            # both rounds itself and compares the verdict. A validator that only
            # inspected the leader's payload for a well-formed shape would be
            # letting the leader decide alone.
            return tiebreak_agrees(leader_fn(), leaders_res.calldata)

        res = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

        # Re-derived from the stored rounds rather than trusted, so a stored
        # verdict can never contradict the record beneath it.
        forward = normalise_side(res.get("forward", ""))
        reverse = normalise_side(res.get("reverse", ""))
        verdict = combine_rounds(forward, reverse)

        self.comparisons.append(
            Comparison(
                pair_id=u256(int(pair_id)),
                verdict=verdict,
                forward=forward,
                reverse=reverse,
                why_forward=sanitise_reason(res.get("why_forward", "")),
                why_reverse=sanitise_reason(res.get("why_reverse", "")),
                at=str(gl.message_raw["datetime"]),
            )
        )

        # Re-read the pair. The append above may have moved the underlying
        # slot, and a storage object is a view on a slot rather than a copy.
        q = self.pairs[int(pair_id)]
        if verdict == A:
            q.n_a = u256(int(q.n_a) + 1)
        elif verdict == B:
            q.n_b = u256(int(q.n_b) + 1)
        else:
            q.n_tied = u256(int(q.n_tied) + 1)

    # -- views --------------------------------------------------------------

    @gl.public.view
    def count(self) -> u256:
        return u256(len(self.pairs))

    @gl.public.view
    def verdict(self, pair_id: u256) -> str:
        """a, b or tied. Empty string when the pair has never been compared."""
        self._pair(pair_id)
        cid = self._last_comparison(int(pair_id))
        if cid < 0:
            return ""
        return str(self.comparisons[cid].verdict)

    @gl.public.view
    def latest(self, pair_id: u256) -> dict:
        p = self._pair(pair_id)
        cid = self._last_comparison(int(pair_id))
        if cid < 0:
            return {
                "compared": False,
                "criterion": str(p.criterion),
                "item_a": str(p.item_a),
                "item_b": str(p.item_b),
                "verdict": "",
                "rounds": {},
                "reasons_are_leader_supplied": True,
                "at": "",
            }
        c = self.comparisons[cid]
        return {
            "compared": True,
            "criterion": str(p.criterion),
            "item_a": str(p.item_a),
            "item_b": str(p.item_b),
            "verdict": str(c.verdict),
            "rounds": {
                "forward": str(c.forward),
                "reverse": str(c.reverse),
                "why_forward": str(c.why_forward),
                "why_reverse": str(c.why_reverse),
            },
            # The two why_ strings are chosen by the leader and are not part of
            # consensus. Saying so in the view stops a consumer mistaking them
            # for facts the network agreed on.
            "reasons_are_leader_supplied": True,
            "at": str(c.at),
        }

    @gl.public.view
    def stability(self, pair_id: u256) -> dict:
        """How often this pair comes back tied.

        A high tied_pct is a statement about the CRITERION, not about the
        network: it means the criterion does not discriminate between these
        items, which is worth knowing before building a ranking on top of it.
        """
        p = self._pair(pair_id)
        n_a = int(p.n_a)
        n_b = int(p.n_b)
        n_tied = int(p.n_tied)
        total = n_a + n_b + n_tied
        return {
            "comparisons": total,
            "a": n_a,
            "b": n_b,
            "tied": n_tied,
            "tied_pct": pct_text(n_tied, total),
            "tied_pct_scaled": pct_scaled(n_tied, total),
            "scale": 10,
        }

    # -- internals ----------------------------------------------------------

    def _pair(self, pair_id: u256):
        """Bounds-checked lookup, used by every read.

        Two things go wrong without it. An id past the end raises a raw
        IndexError, which the runtime reports as a contract error rather than a
        readable user error. And a NEGATIVE id silently returns the last record,
        so asking for pair -1 hands back the newest pair as if it were the one
        requested. The second is worse, because nothing fails.
        """
        i = int(pair_id)
        if i < 0 or i >= len(self.pairs):
            raise gl.vm.UserError("no such pair")
        return self.pairs[i]

    def _last_comparison(self, pair_id: int) -> int:
        """The index of the most recent comparison for this pair, or -1.

        Walks backwards and filters on pair_id. A lookup that ignored the
        parent id would hand back another pair's verdict, correctly formatted,
        with nothing failing anywhere.

        An INDEX, never the record. A storage object is a view on a slot rather
        than a copy, and indexing the array builds a fresh view every time, so a
        record handed back here could never be matched against the array again.
        """
        for k in range(len(self.comparisons) - 1, -1, -1):
            if int(self.comparisons[k].pair_id) == pair_id:
                return k
        return -1
