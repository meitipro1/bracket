# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
Winnow — a batch, sorted into what to act on, what to discard, and what a human
must look at
==============================================================================

WHAT IT IS
    Sort N items into three buckets against a written standard: accept, reject,
    review. Consensus is on the PARTITION.

    No ordering at all. This is the coarsest rung of the ladder and the one most
    applications actually want, because most workflows do not need a ranking --
    they need to know what to act on, what to discard, and what a human has to
    look at.

HOW CONSENSUS IS USED
    A custom validator, and the rule has one deliberate allowance that is the
    heart of the design: bucket by bucket, with exactly ONE boundary item
    forgiven, and only ever through REVIEW.

        accept  <->  review     forgiven, once
        reject  <->  review     forgiven, once
        accept  <->  reject     never forgiven

    REVIEW is the uncertain middle. An item genuinely near a boundary can
    honestly land either side of it, and two validators disagreeing about one
    such item is not a disagreement about the standard: it is the standard
    working.

    An allowance that forgave ANY single difference would let two nodes disagree
    about whether an item passes or fails and still settle -- the worst possible
    outcome, because the record would look decisive. Routing the allowance
    through REVIEW means the only forgiven disagreement is one about certainty,
    never one about direction.

THE REFUSAL PATH
    Every batch carries a max_review_pct declared at registration. If more than
    that fraction of items land in review, the whole batch is stored and marked
    standard_too_vague. A standard that sends eighty percent of a batch to a
    human has not triaged anything, and the contract should say so rather than
    quietly hand back a pile of work.

WHY THIS IS NOT A THIN LLM WRAPPER
    The model labels. It never decides whether the run counts. The agreement
    rule, the one-item allowance, and the vagueness threshold are all pure
    functions against values frozen on chain before the model ran.

    Winnow calls Tiebreak's question internally: is this difference real, or is
    it noise? Here it decides whether an item belongs in the uncertain middle.
"""

from genlayer import *
from dataclasses import dataclass


# --- PURE RULES BEGIN -------------------------------------------------------

MARKUP = "<>{}`[]\\"

#: Error classification. Only one class can occur inside the block here: these
#: contracts make no web request, so there is no external 4xx to distinguish
#: from a transient 5xx, and every business-logic refusal happens in the
#: DETERMINISTIC half where it surfaces to the caller as a plain UserError.
#: What is left is a model that answered with something that is not an object at
#: all, and the correct response to that is to disagree and force rotation --
#: agreeing on broken model output would lock bad state.
ERROR_LLM = "[LLM_ERROR]"

ACCEPT = "accept"
REJECT = "reject"
REVIEW = "review"
BUCKETS = (ACCEPT, REJECT, REVIEW)

TOO_VAGUE = "standard_too_vague"

STANDARD_MIN = 12
STANDARD_MAX = 300
ITEM_MAX = 600
REASON_MAX = 300
MIN_ITEMS = 2
MAX_ITEMS = 12


def normalise_bucket(raw):
    """Map whatever the model said onto exactly accept, reject or review.

    Anything unrecognised becomes REVIEW, which is the safe direction: an
    unreadable label sends the item to a human rather than silently accepting or
    discarding it. Mapping an unknown answer onto accept or reject would let a
    malformed response act on an item.
    """
    s = str(raw).strip().lower()
    if s in (ACCEPT, "accepted", "pass", "yes"):
        return ACCEPT
    if s in (REJECT, "rejected", "fail", "no"):
        return REJECT
    return REVIEW


def parse_partition(text, n):
    """Pipe-joined labels to a normalised partition, or None on a count mismatch."""
    parts = str(text).split("|")
    if len(parts) != n:
        return None
    return [normalise_bucket(p) for p in parts]


def partition_agrees(mine, theirs, n):
    """Bucket by bucket, with exactly one boundary item forgiven through review.

    Symmetric by construction: the comparison at each index is an equality, and
    the forgiveness test asks whether REVIEW is on EITHER side, so swapping the
    arguments cannot change the answer.
    """
    if len(mine) != n or len(theirs) != n:
        return False
    drifted = 0
    for i in range(n):
        if mine[i] == theirs[i]:
            continue
        if REVIEW not in (mine[i], theirs[i]):
            return False              # accept <-> reject, never forgiven
        drifted += 1
        if drifted > 1:               # one boundary item, not two
            return False
    return True


def review_count(partition):
    n = 0
    for b in partition:
        if b == REVIEW:
            n += 1
    return n


def is_too_vague(partition, max_review_pct):
    """More than the declared fraction in review means nothing was triaged.

    Integer arithmetic throughout: no float crosses any boundary here, and a
    percentage computed in floats would compare differently on two nodes at the
    exact threshold.
    """
    n = len(partition)
    if n == 0:
        return False
    return review_count(partition) * 100 > int(max_review_pct) * n


def canonical_partition(partition):
    """The string that crosses consensus: the buckets, in item order."""
    return "|".join(partition)


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


def join_reasons(values, n):
    """Per-item reasons as one pipe-joined string, padded to n.

    Pipes inside a reason would corrupt the split, so they are stripped on the
    way in rather than escaped: the reasons are display text, not data anything
    acts on.
    """
    out = []
    for i in range(n):
        raw = values[i] if i < len(values) else ""
        out.append(sanitise_reason(str(raw).replace("|", " "), 120))
    return "|".join(out)


def build_prompt(standard, items_block, n):
    return (
        "You are triaging " + str(n) + " items against one standard.\n"
        "\n"
        "Standard: " + standard + "\n"
        "\n"
        "Items, by index:\n"
        + items_block + "\n"
        "\n"
        "Put every item in exactly one bucket: accept, reject, or review.\n"
        "Use review when the standard does not clearly decide the item.\n"
        "Reply with JSON: {\"buckets\": [one label per item, in index order], "
        "\"why\": [one short reason per item, in index order]}\n"
    )


# --- PURE RULES END ---------------------------------------------------------


@allow_storage
@dataclass
class Item:
    batch_id: u256
    idx: u256
    text: str


@allow_storage
@dataclass
class Label:
    triage_id: u256
    item_idx: u256
    bucket: str
    why: str


@allow_storage
@dataclass
class Triage:
    batch_id: u256
    canonical: str
    refusal: str
    at: str


@allow_storage
@dataclass
class Batch:
    author: Address
    standard: str
    max_review_pct: u256
    n_items: u256


class Contract(gl.Contract):
    batches: DynArray[Batch]
    items: DynArray[Item]
    triages: DynArray[Triage]
    labels: DynArray[Label]

    def __init__(self):
        pass

    # -- writes -------------------------------------------------------------

    @gl.public.write
    def define(self, standard: str, items: str, max_review_pct: u256) -> None:
        """Freeze the standard, the items, and how much uncertainty is tolerable."""
        s = " ".join(str(standard).split())
        if len(s) < STANDARD_MIN or len(s) > STANDARD_MAX:
            raise gl.vm.UserError("standard must be 12 to 300 characters")

        parts = split_items(items)
        if len(parts) < MIN_ITEMS or len(parts) > MAX_ITEMS:
            raise gl.vm.UserError("a batch holds 2 to 12 items")
        for p in parts:
            if len(p) > ITEM_MAX:
                raise gl.vm.UserError("an item may be at most 600 characters")
        if len(set(parts)) != len(parts):
            raise gl.vm.UserError("items must be distinct")

        pct = int(max_review_pct)
        if pct < 0 or pct > 100:
            raise gl.vm.UserError("max_review_pct must be 0 to 100")

        batch_id = len(self.batches)
        self.batches.append(
            Batch(
                author=gl.message.sender_address,
                standard=s,
                max_review_pct=u256(pct),
                n_items=u256(len(parts)),
            )
        )
        for i in range(len(parts)):
            self.items.append(
                Item(batch_id=u256(batch_id), idx=u256(i), text=parts[i])
            )

    @gl.public.write
    def triage(self, batch_id: u256) -> None:
        """Label, agree with one boundary item forgiven, then store."""
        b = self._batch(batch_id)

        standard = str(b.standard)
        n = int(b.n_items)
        max_pct = int(b.max_review_pct)
        texts = self._item_texts(int(batch_id))
        items_block = "\n".join(str(i) + ". " + texts[i] for i in range(n))

        def leader_fn():
            out = gl.nondet.exec_prompt(
                build_prompt(standard, items_block, n), response_format="json"
            )
            if not isinstance(out, dict):
                raise gl.vm.UserError(
                    ERROR_LLM + " prompt returned " + type(out).__name__
                )
            buckets = out.get("buckets", [])
            if not isinstance(buckets, list):
                buckets = []
            # Labels are normalised but NOT padded. A model that labelled three
            # of four items did not do the task, and quietly filling the gap
            # with `review` would turn a malformed answer into a plausible one.
            # The wrong count travels as the wrong count and is refused.
            labels = [normalise_bucket(b) for b in buckets]
            why = out.get("why", [])
            if not isinstance(why, list):
                why = []
            return {
                "buckets": canonical_partition(labels),
                "why": join_reasons(why, n),
            }

        def validator_fn(leaders_res):
            # A leader that did not return is a leader whose model misbehaved --
            # the only error class reachable inside this block. Disagree, which
            # forces rotation; agreeing on broken model output would lock it in.
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            mine = parse_partition(leader_fn().get("buckets", ""), n)
            theirs = parse_partition(leaders_res.calldata.get("buckets", ""), n)
            if mine is None or theirs is None:
                return False
            return partition_agrees(mine, theirs, n)

        res = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

        partition = parse_partition(res.get("buckets", ""), n)
        if partition is None:
            raise gl.vm.UserError("the bucket count does not match the item count")

        refusal = TOO_VAGUE if is_too_vague(partition, max_pct) else ""
        reasons = str(res.get("why", "")).split("|")

        triage_id = len(self.triages)
        self.triages.append(
            Triage(
                batch_id=u256(int(batch_id)),
                canonical=canonical_partition(partition),
                refusal=refusal,
                at=str(gl.message_raw["datetime"]),
            )
        )
        for i in range(n):
            self.labels.append(
                Label(
                    triage_id=u256(triage_id),
                    item_idx=u256(i),
                    bucket=partition[i],
                    why=sanitise_reason(reasons[i] if i < len(reasons) else ""),
                )
            )

    # -- views --------------------------------------------------------------

    @gl.public.view
    def count(self) -> u256:
        return u256(len(self.batches))

    @gl.public.view
    def partition(self, batch_id: u256) -> str:
        """"accept|review|reject|accept", in item order, or "" before any run."""
        self._batch(batch_id)
        tid = self._last_triage(int(batch_id))
        if tid < 0:
            return ""
        return str(self.triages[tid].canonical)

    @gl.public.view
    def bucket(self, batch_id: u256, item_idx: u256) -> str:
        """One item's bucket, for a consuming contract.

        Empty when the batch has not been triaged, so a consumer has one branch
        rather than two.
        """
        b = self._batch(batch_id)
        i = int(item_idx)
        if i < 0 or i >= int(b.n_items):
            raise gl.vm.UserError("no such item")
        tid = self._last_triage(int(batch_id))
        if tid < 0:
            return ""
        parts = str(self.triages[tid].canonical).split("|")
        if i >= len(parts):
            return ""
        return parts[i]

    @gl.public.view
    def latest(self, batch_id: u256) -> dict:
        b = self._batch(batch_id)
        tid = self._last_triage(int(batch_id))
        texts = self._item_texts(int(batch_id))
        if tid < 0:
            return {
                "triaged": False,
                "standard": str(b.standard),
                "max_review_pct": int(b.max_review_pct),
                "canonical": "",
                "refusal": "",
                "labels": [],
                "reasons_are_leader_supplied": True,
                "at": "",
            }
        t = self.triages[tid]
        rows = []
        for j in range(len(self.labels)):
            lb = self.labels[j]
            if int(lb.triage_id) != tid:
                continue
            idx = int(lb.item_idx)
            rows.append(
                {
                    "item_idx": idx,
                    "item": texts[idx] if idx < len(texts) else "",
                    "bucket": str(lb.bucket),
                    "why": str(lb.why),
                }
            )
        return {
            "triaged": True,
            "standard": str(b.standard),
            "max_review_pct": int(b.max_review_pct),
            "canonical": str(t.canonical),
            # "standard_too_vague" means more than the declared fraction landed
            # in review: the standard did not triage anything.
            "refusal": str(t.refusal),
            "labels": rows,
            "reasons_are_leader_supplied": True,
            "at": str(t.at),
        }

    # -- internals ----------------------------------------------------------

    def _batch(self, batch_id: u256):
        i = int(batch_id)
        if i < 0 or i >= len(self.batches):
            raise gl.vm.UserError("no such batch")
        return self.batches[i]

    def _item_texts(self, batch_id: int):
        out = []
        for j in range(len(self.items)):
            it = self.items[j]
            if int(it.batch_id) == batch_id:
                out.append(str(it.text))
        return out

    def _last_triage(self, batch_id: int) -> int:
        """The index of the most recent triage for this parent, or -1.

        An INDEX, deliberately, never the object. A storage object is a
        view on a slot rather than a copy, and indexing the array builds a
        fresh view every time, so `self.triages[i] is obj` is always False on a
        node. Carrying the index instead is the only thing that survives.
        """
        for j in range(len(self.triages) - 1, -1, -1):
            t = self.triages[j]
            if int(t.batch_id) == batch_id:
                return j
        return -1
