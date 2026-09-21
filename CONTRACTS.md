# Contracts

One page each: purpose, consensus, state, API, reuse. Written so a reviewer can
judge the design without opening the source.

All four share the same shape. Every collection is a top level contract field
and child records carry a parent id, because a storage dataclass cannot contain
a collection. Every public parameter is `str`, `u256` or `bool` — collections
arrive pipe-joined. Every block returns a flat dict of `str`. Every view
bounds-checks its id and rejects negatives explicitly. Every `raise` is
`gl.vm.UserError`.

---

## Tiebreak — `contracts/tiebreak.py`

### Purpose

Decide whether two items are distinguishable under a written criterion, or
whether any ordering between them would be noise. Returns `a`, `b` or `tied`.

`tied` is not a failure. It is the network agreeing, precisely, that the
criterion does not separate these two.

### The failure it catches

Position bias. Language models systematically favour whichever option appears
first. Validator consensus cannot catch it, because every validator builds the
prompt from the same template, presents the items in the same order, inherits
the same bias, and they all agree on an artefact of the prompt.

### Consensus

`gl.vm.run_nondet_unsafe`. Two prompts run sequentially inside one block —
sequential prompts are legal, nested non-deterministic blocks are not.

    forward round   A shown first, B second
    reverse round   B shown first, A second

Both come from one template with a single direction parameter. If the prompts
differed in tone, length or specificity, a disagreement between them would
measure the prompts rather than the model. A test asserts they have identical
line structure and share every scaffolding phrase.

Only `a`-then-`a` and `b`-then-`b` are position-independent. The other seven
combinations become `tied`.

The validator has two layers. **Layer 1** is a free internal honesty check:
`combine_rounds` is pure, so a validator confirms the leader's own two rounds
produce the verdict it reported without running a prompt. **Layer 2** compares
only the verdict, never the raw rounds, because two honest nodes may differ on
one round and still land on the same verdict.

### State

| Field | Type | Note |
|---|---|---|
| `pairs` | `DynArray[Pair]` | append only |
| `comparisons` | `DynArray[Comparison]` | flat, each carries `pair_id` |
| **Pair** | | |
| `author` | `Address` | |
| `criterion` | `str` | 12–300 chars, frozen |
| `item_a` `item_b` | `str` | frozen, capped at 600 |
| `n_a` `n_b` `n_tied` | `u256` | counters for `stability()` |
| **Comparison** | | |
| `pair_id` | `u256` | which pair this belongs to |
| `verdict` | `str` | `a` \| `b` \| `tied` |
| `forward` `reverse` | `str` | the two rounds, for the record |
| `why_forward` `why_reverse` | `str` | leader supplied, sanitised, NOT consensus |
| `at` | `str` | `gl.message_raw["datetime"]` |

### API

```python
register(criterion: str, item_a: str, item_b: str)   # freeze the pair
compare(pair_id: u256)                                # both orders, one block

verdict(pair_id)    -> str    # a | b | tied
latest(pair_id)     -> dict   # the verdict and both rounds behind it
stability(pair_id)  -> dict   # {comparisons, a, b, tied, tied_pct, ...}
count()             -> u256
```

A high `tied_pct` is a statement about the **criterion**, not about the network:
it means the criterion does not discriminate between these items, which is worth
knowing before building a ranking on top of it. It is returned as a canonical
decimal string plus a scaled integer, because no float crosses calldata.

### Reuse

Anywhere an ordering is about to be built and you need to know whether the
ordering is real: grant review, hiring shortlists, model evaluation, dispute
severity, any leaderboard whose top two are close.

---

## Slate — `contracts/slate.py`

### Purpose

Order N items against a written criterion, collapsing items that cannot be told
apart into a shared rank. The output is a banded ordering: rank 1, rank 2,
rank 2, rank 4.

### Consensus

Comparing the raw ordering with `strict_eq` never settles: two honest validators
swap two adjacent near-equal items roughly every time. Loosening to a
prompt-based principle accepts an ordering that reversed the top two, which is
the only part anyone cares about.

Instead the block returns an order and a score per item, and the **contract**
bands those scores deterministically against a `closeness` threshold frozen at
registration. Consensus compares the banded rank vector, canonicalised to one
string.

    "2:1|0:2|1:2|3:3"      items 0 and 1 are tied at rank 2

Banding is transitive along the run: if a is close to b and b is close to c, all
three share a band even when a and c are further apart than the threshold. The
alternative depends on which pair you compare first and is not deterministic in
any useful sense.

Item indices are sorted **within** each band. Between bands the order is the
whole answer; inside a band the contract has already declined to separate them.

### Refusal paths

| Condition | Result |
|---|---|
| every item lands in one band | `undifferentiated`, stored and exposed |
| the returned order is not a permutation of 0..n-1 | rejected, `UserError` |
| the score count does not match the item count | rejected, `UserError` |
| validators produce different banded vectors | consensus fails, nothing is written |

### State

| Field | Type | Note |
|---|---|---|
| `slates` | `DynArray[Slate]` | |
| `items` | `DynArray[Item]` | flat, carries `slate_id` and `idx` |
| `rankings` | `DynArray[Ranking]` | flat, carries `slate_id` |
| `placements` | `DynArray[Placement]` | flat, carries `ranking_id` |
| **Slate** | | `criterion` `str` frozen · `closeness` `str` (threshold as text) · `n_items` `u256` (2–12) · `author` `Address` |
| **Placement** | | `ranking_id` `item_idx` `rank` `band`, all `u256` |

### API

```python
define(criterion: str, items: str, closeness: str)   # items pipe-joined
rank(slate_id: u256)                                  # order, band, agree, store

order(slate_id)   -> str    # "2:1|0:2|1:2|3:3", the canonical form
latest(slate_id)  -> dict   # placements with item text, plus refusal reason
slate(slate_id)   -> dict   # the frozen definition
count()           -> u256
```

`items` is a single pipe-joined string, not `list[str]`. A list parameter is
close enough to a documented GenVM restriction to be a bet rather than a
decision, and this family does not take that bet.

### Reuse

Grant rounds, proposal review, model leaderboards — anywhere a ranking is
published and the ties in it matter as much as the order.

---

## Cutline — `contracts/cutline.py`

### Purpose

Select the best K of N against a written criterion. Consensus is on set
membership only.

### Why this is deliberately looser than Slate

For a grant round, a shortlist or a payout tier, one question matters: who got
in. Whether the third and fourth entrant were in that order is not a fact anyone
acts on, and demanding agreement about it would reject correct work for no
benefit. Cutline throws away more than Slate does, on purpose.

    what crosses consensus    "0|3|7"    who is in, not who is first

### The boundary problem

If item K and item K+1 are indistinguishable the cut is arbitrary. The network
will agree on a selection, but the selection is noise dressed as a decision —
worse than failing, because it looks authoritative. Cutline bands the scores
exactly as Slate does, then inspects the boundary. What happens next is declared
at registration:

| `on_tie` | Behaviour when the cut falls inside a band |
|---|---|
| `refuse` | store the attempt, mark it `cut_is_arbitrary`, select nobody. Correct when K is a hard budget. |
| `expand` | include the whole tied band, so the selection may exceed K. Correct when K is a target and fairness matters more than the exact count. |

Neither is right in general, which is precisely why it is a parameter rather
than a hardcoded policy.

### State

| Field | Type | Note |
|---|---|---|
| `cutlines` | `DynArray[Cutline]` | `criterion` · `closeness` · `on_tie` · `k` · `n_items` · `author` |
| `items` | `DynArray[Item]` | flat, carries `cutline_id` and `idx` |
| `selections` | `DynArray[Selection]` | flat, carries `cutline_id`, plus `canonical` and `refusal` |
| `picks` | `DynArray[Pick]` | flat, carries `selection_id` |

### API

```python
define(criterion: str, items: str, k: u256,
       closeness: str, on_tie: str)                 # on_tie: refuse | expand
select(cutline_id: u256)

selected(cutline_id)  -> str    # "0|3|7", sorted indices, or "" when refused
latest(cutline_id)    -> dict   # selection, item text, whether the cut was arbitrary
count()               -> u256
```

`selected()` returns an empty string rather than raising when the cut was
refused, so a consuming contract has one branch to handle instead of two.

### Reuse

Grant rounds with a fixed budget, shortlists, payout tiers, any "top K" where
being just outside the line has consequences.

---

## Winnow — `contracts/winnow.py`

### Purpose

Sort N items into three buckets against a written standard: `accept`, `reject`,
`review`. Consensus is on the partition. No ordering at all.

This is the coarsest rung and the one most applications actually want, because
most workflows do not need a ranking — they need to know what to act on, what to
discard, and what a human has to look at.

### Consensus

A custom validator, bucket by bucket, with exactly one boundary item forgiven
and only ever through `review`:

    accept <-> review    forgiven, once
    reject <-> review    forgiven, once
    accept <-> reject    never forgiven

`review` is the uncertain middle. An item genuinely near a boundary can honestly
land either side of it, and two validators disagreeing about one such item is
not a disagreement about the standard: it is the standard working.

An allowance that forgave *any* single difference would let two nodes disagree
about whether an item passes or fails and still settle — the worst possible
outcome, because the record would look decisive.

Labels are normalised but never padded. A model that labelled three of four
items did not do the task, and filling the gap with `review` would turn a
malformed answer into a plausible one.

### Refusal path

Every batch carries a `max_review_pct` declared at registration. If more than
that fraction of items land in `review`, the batch is stored and marked
`standard_too_vague`. A standard that sends eighty percent of a batch to a human
has not triaged anything, and the contract says so rather than quietly handing
back a pile of work.

### State

| Field | Type | Note |
|---|---|---|
| `batches` | `DynArray[Batch]` | `standard` · `max_review_pct` · `n_items` · `author` |
| `items` | `DynArray[Item]` | flat, carries `batch_id` and `idx` |
| `triages` | `DynArray[Triage]` | flat, carries `batch_id`, plus `canonical` and `refusal` |
| `labels` | `DynArray[Label]` | flat, carries `triage_id`, one per item |

### API

```python
define(standard: str, items: str, max_review_pct: u256)
triage(batch_id: u256)

partition(batch_id)             -> str    # "accept|review|reject|accept"
latest(batch_id)                -> dict   # the partition with item text and reasons
bucket(batch_id, item_idx)      -> str    # one item, for a consuming contract
count()                         -> u256
```

`bucket()` returns an empty string before a triage rather than raising, so a
consumer has one branch rather than two.

### Reuse

Moderation queues, submission triage, support ticket routing, any batch where
the useful output is three piles rather than a ranking.

---

## The shared library

[`lib/bracket_consensus.py`](lib/bracket_consensus.py) holds the agreement rules on
their own. It is **not** an imported module: a GenLayer contract is a single
Python file inside the GenVM, with no `pip install` and no cross-file import at
deploy time, so each contract inlines the helpers it needs. The library exists so
the rules can be read and lifted without opening a whole contract.

`tests/test_logic.py` asserts the library has not drifted from the contracts,
because a reference copy that quietly disagrees with the thing it documents is
worse than no reference copy.

**Every rule in it is symmetric.** `agrees(a, b) == agrees(b, a)`, always, with
a parametrised test asserting it for each. An asymmetric rule makes consensus
depend on which node happened to be elected leader, which is a bug that only
shows up under load and is very hard to read back out of a failed transaction.
