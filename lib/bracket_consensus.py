"""The agreement rules of the Bracket family, on their own.

This file is NOT imported by the contracts. A GenLayer contract is a single
Python file inside the GenVM: there is no pip install and no cross-file import
at deploy time, so each contract inlines the helpers it needs. This file exists
so the rules can be read, tested and lifted without opening a whole contract.

Everything here is pure. No storage, no network, no model. That is the point:
these are the functions a validator runs to decide whether two nodes agreed,
and a function that decides agreement must be deterministic or it decides
nothing.

EVERY RULE IN HERE IS SYMMETRIC. agrees(a, b) == agrees(b, a), always. An
asymmetric rule makes consensus depend on which node happened to be elected
leader, which is a bug that only shows up under load and is very hard to read
back out of a failed transaction.
"""

#: No imports, deliberately. Everything here runs inside a GenVM contract as
#: inlined source, and the contracts avoid the stdlib entirely: NaN is detected
#: with `v != v` and infinity by comparison against INF, exactly as they do it.
#: A helper that behaves differently here than it does on chain would make this
#: file worse than useless.

INF = float("inf")

# -- the closed vocabularies -------------------------------------------------
#
# Nothing outside these sets ever reaches storage or a comparison. A model is
# free to answer anything it likes; normalise_side is where that freedom stops.

A = "a"
B = "b"
NEITHER = "neither"
TIED = "tied"

ACCEPT = "accept"
REJECT = "reject"
REVIEW = "review"
BUCKETS = (ACCEPT, REJECT, REVIEW)

REFUSE = "refuse"
EXPAND = "expand"
ON_TIE = (REFUSE, EXPAND)

UNDIFFERENTIATED = "undifferentiated"


# -- Tiebreak ----------------------------------------------------------------


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
    """Only a winner that survives BOTH presentation orders is real.

    Nine combinations, two of them position-independent. Everything else is
    TIED, including the case where the model simply names whichever item it saw
    first in each round -- that is position bias in its purest form, and naming
    it is the entire reason this contract exists.
    """
    f, r = normalise_side(forward), normalise_side(reverse)
    if f == A and r == A:
        return A
    if f == B and r == B:
        return B
    return TIED


def tiebreak_agrees(mine, theirs):
    """Two layers, and the order of them matters.

    Layer 1 is a free internal honesty check. combine_rounds is pure, so a
    validator can confirm the leader's own two rounds actually produce the
    verdict it reported without running a single prompt. A malformed or
    dishonest proposal dies before any inference is spent on it.

    Layer 2 compares ONLY the verdict, never the raw rounds. Two honest nodes
    may differ on one round and still land on the same verdict; forcing the
    rounds to match would reject correct work.
    """
    mine_v = str(mine.get("verdict", ""))
    theirs_v = str(theirs.get("verdict", ""))

    for side in (mine, theirs):
        v = str(side.get("verdict", ""))
        if v not in (A, B, TIED):
            return False
        if combine_rounds(side.get("forward", ""), side.get("reverse", "")) != v:
            return False

    return mine_v == theirs_v


# -- scores, bands, orderings ------------------------------------------------


def parse_scores(text, n):
    """Pipe-joined text to floats. Returns None on anything unusable.

    Non-finite is a failure, never a value. float("1e400") is infinity, and
    infinity compares <= against every threshold ever written, so an infinity
    that reached banding would silently collapse every band into one.
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
        # NaN compares false against itself; "1e400" overflows straight to
        # infinity, and infinity satisfies every <= threshold ever written, so
        # an infinity that reached banding would collapse every band into one.
        if v != v or v == INF or v == -INF:
            return None
        out.append(v)
    return out


def band_scores(scores, closeness):
    """Adjacent scores within `closeness` share a band.

    Banding is transitive along the sorted run, and that is deliberate: if a is
    close to b and b is close to c, all three share a band even when a and c are
    further apart than the threshold. The alternative is a banding that depends
    on which pair you compare first, which is not deterministic in any useful
    sense and so cannot be the thing consensus rests on.

    `scores` arrives in rank order, best first.
    """
    bands, current = [], 1
    for i, s in enumerate(scores):
        if i > 0 and abs(scores[i - 1] - s) > closeness:
            current += 1
        bands.append(current)
    return bands


def is_permutation(order, n):
    """Reject anything that is not exactly 0..n-1, once each.

    A model that repeats an index has dropped an item, and a ranking that
    silently omits an item is worse than no ranking: it looks complete.
    """
    if len(order) != n:
        return False
    seen = set()
    for i in order:
        if not isinstance(i, int) or isinstance(i, bool):
            return False
        if i < 0 or i >= n or i in seen:
            return False
        seen.add(i)
    return True


def canonical_order(order, bands):
    """The string that crosses consensus, and nothing else does.

    "2:1|0:2|1:2|3:3" -- items 0 and 1 share rank 2. The scores that produced it
    are discarded before the comparison rather than tolerated during it.

    Item indices are sorted WITHIN each band, because two honest validators will
    swap two adjacent near-equal items roughly every time, and if that swap
    changed this string the contract would never settle. Between bands the order
    is meaningful and is preserved.
    """
    out = []
    i = 0
    while i < len(order):
        j = i
        while j < len(order) and bands[j] == bands[i]:
            j += 1
        for idx in sorted(order[i:j]):
            out.append("%d:%d" % (idx, bands[i]))
        i = j
    return "|".join(out)


def canonical_selection(selected):
    """Sorted indices. Membership without order.

    Cutline throws away more than Slate does, on purpose: for a shortlist the
    only fact anyone acts on is who got in.
    """
    return "|".join(str(i) for i in sorted(selected))


def cut_at(bands, k, on_tie):
    """Where the line falls, and whether it fell inside a tie.

    Returns (selected_count, arbitrary) given banded scores in rank order.

    If item K and item K+1 share a band the cut is arbitrary, and an arbitrary
    cut that still returns a selection is worse than a refusal, because it looks
    authoritative. What happens instead is declared at registration rather than
    hardcoded here: choosing for the caller would be making a governance
    decision on their behalf.
    """
    if k <= 0:
        return 0, False
    if k >= len(bands):
        return len(bands), False
    if bands[k - 1] != bands[k]:
        return k, False
    if on_tie == REFUSE:
        return 0, True
    n = k
    while n < len(bands) and bands[n] == bands[k - 1]:
        n += 1
    return n, False


# -- Winnow ------------------------------------------------------------------


def partition_agrees(mine, theirs, n):
    """Bucket by bucket, with exactly one boundary item forgiven.

    REVIEW is the uncertain middle. An item genuinely near a boundary can
    honestly land either side of it, and two validators disagreeing about one
    such item is not a disagreement about the standard -- it is the standard
    working.

    An item flipping ACCEPT to REJECT is a different thing entirely. Nothing
    near a boundary crosses two buckets at once. Routing the allowance through
    REVIEW means the only forgiven disagreement is one about certainty, never
    one about direction: an allowance that forgave any single difference would
    let two nodes disagree about whether an item passes or fails and still
    settle, which is the worst possible outcome because the record would look
    decisive.
    """
    if len(mine) != n or len(theirs) != n:
        return False
    drifted = 0
    for i in range(n):
        if mine[i] == theirs[i]:
            continue
        if REVIEW not in (mine[i], theirs[i]):
            return False
        drifted += 1
        if drifted > 1:
            return False
    return True


# -- shared ------------------------------------------------------------------

MARKUP = "<>{}`[]\\"


def sanitise_reason(raw, cap=300):
    """Strip markup and control characters from leader-supplied prose.

    The reasons are deliberately excluded from consensus -- two honest readers
    describe the same shortfall differently, and comparing prose would stall
    every run. That means a leader picks them freely, so they are treated as
    untrusted text on the way into storage. Nothing in any contract acts on
    them, and every view that returns them says so.
    """
    out = []
    for ch in str(raw):
        if ch in MARKUP:
            continue
        # Control characters become spaces rather than vanishing, so two words
        # either side of one do not silently fuse into a different word.
        if ord(ch) < 32 or ord(ch) == 127:
            out.append(" ")
        else:
            out.append(ch)
    return " ".join("".join(out).split())[:cap]
