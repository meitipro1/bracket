# Decisions

Every design decision with its reasoning, every bug found while building, with
the error it produced, and the honest limits of each contract.

---

## The one idea

Do not ask the network to agree on a measurement. Ask it to agree on a
structure, and derive the structure deterministically from the measurement.

Two validators will never agree that a thing scores 7.3 rather than 7.6. They
will agree, easily and repeatedly, that it beats the thing next to it. Every
contract here takes a fine-grained judgment and collapses it into a coarser
structure *before* consensus sees it. The structure crosses the boundary; the
numbers behind it are discarded.

The coarser the structure, the more reliably consensus settles, so the ladder
runs from Slate (an ordering, with ties banded) down to Tiebreak (whether two
items differ at all). Choose the coarsest rung your application can use.

---

## Why Tiebreak is the atom

The other three call the same question internally: *is this difference real, or
is it noise?* Slate uses it to decide which items share a rank, Cutline to
decide whether the cut falls inside a tie, Winnow to decide whether an item
belongs in the uncertain middle.

That is why Tiebreak was built first and completely, including its mutation
pass, before a line of the other three was written. Its banding and agreement
logic is reused three times, so getting it wrong once would have meant getting
it wrong four times.

---

## Canonicalise, then use the cheapest principle

Slate could have reached for a looser equivalence principle when strict equality
on the raw ordering failed. It does the opposite: it asks what noise is causing
the failure, removes that noise deterministically, and keeps strict equality on
the result.

    block returns    "2|0|1|3" and "88.0|71.5|70.9|40.0"
    contract makes   "2:1|0:2|1:2|3:3"
    consensus on     that string, and nothing else

Faster, cheaper, and far easier to reason about than tolerating noise during the
comparison.

### The ordering inside a band carries no weight

`canonical_order` sorts item indices **within** each band, and this was a real
correction during the build rather than a decision made up front.

The first implementation emitted items in the order the model returned them,
including inside a tied band. A test immediately caught it: two nodes that band
identically but swap two tied items produced different canonical strings and
failed to agree. That is precisely the failure banding exists to remove, so the
first implementation defeated its own purpose.

Between bands the order is the entire answer and is preserved. Inside a band the
contract has already said it will not pretend to separate the items, so the order
there must not decide whether consensus settles.

---

## Why the tie policy is a parameter

If item K and item K+1 are indistinguishable, Cutline's cut is arbitrary. The
network will agree on a selection, but the selection is noise dressed as a
decision, which is worse than failing because it looks authoritative.

    refuse   store the attempt, mark it cut_is_arbitrary, select nobody
    expand   include the whole tied band, so the selection may exceed K

Neither is right in general. `refuse` is correct when K is a hard budget;
`expand` is correct when K is a target and fairness matters more than the exact
count. A contract that silently picked one would be making a governance decision
on the caller's behalf, so it is declared at registration and frozen there.

---

## Why Winnow forgives exactly one item, and only through review

`review` is the uncertain middle. An item genuinely near a boundary can honestly
land either side of it, and two validators disagreeing about one such item is
not a disagreement about the standard: it is the standard working.

An allowance that forgave *any* single difference would let two nodes disagree
about whether an item passes or fails and still settle. That is the worst
possible outcome, because the record would look decisive. Routing the allowance
through `review` means the only forgiven disagreement is one about certainty,
never one about direction:

    accept <-> review    forgiven, once
    reject <-> review    forgiven, once
    accept <-> reject    never forgiven

---

## Refusing is designed, not an error path

Four refusals are first-class results, stored and exposed rather than raised:

| Contract | Refusal | What it means |
|---|---|---|
| Tiebreak | `tied` | the criterion does not separate these two items |
| Slate | `undifferentiated` | every item landed in one band |
| Cutline | `cut_is_arbitrary` | the cut fell inside a tie and the policy was refuse |
| Winnow | `standard_too_vague` | more of the batch went to review than was declared tolerable |

A slate where everything ties is not a broken run, it is a finding. A standard
that sends eighty percent of a batch to a human has not triaged anything, and
the contract should say so rather than quietly hand back a pile of work.

---

## Why none of these read the web

Deliberate. Items and criteria arrive as parameters from the caller.

A previous contract in this line spent an evening failing because several
validators fetched a live page at different moments and never converged.
Removing the web from the design removes an entire class of deployment failure,
and none of these four need it: a slate of proposals, a batch to triage, a pair
to compare — all of it is content the caller already has.

---

## Bugs found while building, and the error each produced

### A mock that matched both rounds at once

The first Tiebreak end-to-end tests keyed their mock answers on the item text,
which appears in **both** prompts — only the order changes. Both rounds
therefore matched the same mock, and a test that was supposed to prove position
bias produced a clean win instead.

    assert c.verdict(0) == "tied"
    AssertionError: assert 'a' == 'tied'

Fixed by keying on the order — `Item a:\n<A>\n\nItem b:` appears only in the
forward round. The lesson generalises: when two prompts differ only in
arrangement, a mock key that names a component is ambiguous by construction.

### The pure section arrived with an indent error

`tests/test_logic.py` executes the marked section of each contract. Splitting on
the marker text alone left the remainder of the marker line — a run of dashes —
as the first line of the extracted body:

    IndentationError: unexpected indent

Fixed by discarding the rest of the marker line.

### Winnow padded a malformed answer into a plausible one

The first `leader_fn` padded a short bucket list up to the item count, filling
the gap with `review`. A model that labelled three of four items would have
produced a complete-looking partition, and the count guard behind it could never
fire. Labels are now normalised but never padded: the wrong count travels as the
wrong count and is refused.

---

## Two mutations that could not be caught, and what that taught

The mutation pass runs every safety property broken on purpose and confirms a
test notices. Three escaped. Two of them were not missing tests — they were
defences that a defence in front of them had already made unobservable.

**Trusting the leader's verdict instead of recomputing it.** Layer 1 of
`tiebreak_agrees` already proves that a proposal's own two rounds produce the
verdict it claims, for both sides. By the time the deterministic half stores
anything, the recomputation provably equals the reported verdict, so replacing
one with the other changes nothing. The test written to catch it **could not
fail**.

**Leaving the arbitrary flag out of Cutline's agreement rule.** Under `refuse`
an arbitrary cut selects nobody, so the flag is derivable from the canonical
string; under `expand` it is always False. The conjunct never changes an
outcome.

A test that cannot fail is worse than no test, because it reports coverage it
does not provide. Both were handled the same way: the redundant defence stays in
the contract, the false claim leaves the mutation table, and the property is
tested where it *is* observable. For Tiebreak that is the paired mutation —
remove the honesty layer **and** trust the verdict, which is what an attacker
would actually have to do — plus a test that the stored rounds are always in the
closed vocabulary.

The third escape was a genuine gap: Cutline's permutation guard and Winnow's
label-count guard had no test of their own, only Slate's. Both now have one. That
is the mutation pass doing exactly what it is for.

---

## Reviewed against the GenLayer authoring guidance

After the build, all four contracts were audited against the `genlayer-dev`
skill's contract-authoring rules. Three things came out of it.

### The validators were already doing independent verification

The guidance is blunt about the commonest mistake: a validator that only checks
the leader's payload for a well-formed shape, an allowed enum value, or a
confidence in range is not consensus. It trusts the leader's substantive answer
completely and proves only that the leader formatted it correctly.

Every validator here re-runs the block itself and compares the derived result —
the verdict, the banded rank vector, the sorted membership, the partition. None
of them inspects the leader's payload for shape alone. That was the design from
the start, and it is the reason the four contracts are worth submitting at all.

### Error classification, and why only one class applies

The guidance prescribes four error prefixes so validators know how to compare
failure paths: `[EXPECTED]`, `[EXTERNAL]`, `[TRANSIENT]`, `[LLM_ERROR]`.

Only the last one can occur inside a block here. These contracts make no web
request, so there is no external 4xx to distinguish from a transient 5xx, and
every business-logic refusal happens in the deterministic half where it reaches
the caller as a plain `UserError` and never touches consensus. Adding the other
three prefixes would be decoration.

`ERROR_LLM` is real and is now used: a model that answers with a string, a list
or nothing at all is classified, and the validator disagrees, which forces
rotation. Agreeing on broken model output would lock bad state.

### The worst bug in the build, and the simulator could not see it

Three contracts looked up their most recent record by scanning the collection
and returning the **record**, then found its index again by identity:

```python
for k in range(len(self.rankings) - 1, -1, -1):
    if self.rankings[k] is ranking:      # always False on a node
        return k
```

`DynArray.__getitem__` in the pinned runner ends in
`self._item_desc.get(items_at, idx * self._item_desc.size)` — it **builds a
fresh view on every access**. A storage object is a view on a slot, not a copy,
so two reads of the same index are two different Python objects and `is` is
never true.

The failure mode is the bad kind. Nothing raises. The lookup returns -1, the
filter matches nothing, and `latest()` hands back an empty `placements` list
that looks like a slate nobody ranked. Storage is correct; the view lies about
it.

`tests/glsim.py` cannot catch this, and no amount of end-to-end testing would
have: its `DynArray` is a real Python list, where identity holds. Only reading
the source catches it, which is exactly what the static shape tests are for.
Two now do:

- `test_no_storage_object_is_compared_by_identity` walks every `is` / `is not`
  comparison and fails on any subscript of `self.…`
- `test_no_lookup_helper_returns_a_storage_object_it_found_by_scanning` requires
  every `_last_*` helper to be annotated `-> int`

Every lookup now carries an index. Tiebreak's was rewritten the same way even
though it had no identity comparison, because a rule that holds in three files
and not the fourth is a rule waiting to be broken.

### A defensive gap the audit found

The first version called `.get()` directly on whatever `exec_prompt` returned.
A model answering with a bare string would have raised `AttributeError` inside
the block — surfacing as a contract error with a raw traceback rather than as a
rotation. Every block now checks the response is an object before touching it,
and four tests drive that path with a string, a list, a number and `None`.

### Two errors in the guidance itself

Worth recording, because they would propagate into any contract written straight
from the skill:

- Its contract skeleton uses `gl.UserError`. In the pinned runner, `UserError`
  lives at `genlayer/vm/__init__.py`, so it is `gl.vm.UserError`. The skill's
  own anti-pattern table gets this right; the skeleton does not.
- The same skeleton uses `gl.message.sender_account`. The SDK declares
  `sender_address` in `genlayer/message.py`, which is what the rest of the skill
  and these contracts use.

Both were settled by reading the pinned SDK on disk rather than the prose.

---

## What the first real deployment taught

Everything above was learned on a workstation. One thing was only learnable on
chain, and it cost three failed transactions.

Slate's first `rank()` came back FINALIZED with **all three validators voting
disagree**. The leader had succeeded; the validators had simply banded the
scores differently. The demo items were the cause: `alpha proposal`,
`beta proposal`, `gamma proposal`, `delta proposal` are labels with no content,
so a model asked which of them "states its tradeoff most clearly" has nothing to
read and invents a score. Different scores on every run, different bands, no
agreement.

The refusal case had passed on the same data, which made it look like the
contract worked. It did not: with `closeness 1000` every score collapses into
one band, so two nodes agree trivially. Passing there proved nothing.

Two things changed, neither of them in a contract:

- The demo items are now real sentences with a genuine difference in clarity —
  one names a number and a cost, one is marketing. A model reads them the same
  way twice.
- `closeness` went from `2.0` to `8.0`. On scores out of 100, a threshold of 2
  is inside the noise of the model's own scoring; the bands were being decided
  by rounding rather than by the items.

This is not a flaw in the design — it is the design working. Slate's whole
premise is that a coarser structure settles where a finer one does not, and the
threshold is the dial. But it means **`closeness` has to be chosen against the
spread you actually expect**, and a slate whose items carry no information will
refuse or fail no matter what it is set to. `scripts/deploy.sh` now carries the
values that settled, so the script and the chain agree.

## Honest limits

**Tiebreak cannot detect a bias both orders share.** It varies presentation
order. A model that prefers longer answers, or answers containing numbers, gives
the same winner in both rounds and Tiebreak calls it real. It measures one
specific artefact, well; it is not a general bias detector.

**Slate's banding depends on scores the model chose.** The threshold is frozen on
chain, but the numbers it is applied to are not. A model that compresses every
score into a narrow range produces one band and an `undifferentiated` result; a
model that spreads them produces clean ranks. The refusal path makes this
visible rather than hiding it, but it does not fix it.

**Transitive banding can chain a long way.** If every adjacent pair is within the
threshold, every item lands in one band even when the ends are far apart. That is
deliberate — the alternative depends on comparison order and is not
deterministic — but it means a smooth distribution of scores collapses entirely.
Choose `closeness` against the spread you expect.

**Cutline's `expand` can select every item.** If the whole slate is one band and
the policy is expand, the selection is everyone. That is the honest answer to
"pick the best 2 of 4 when all four are indistinguishable", but a caller
budgeting for exactly K must use `refuse`.

**Winnow's one-item allowance is a fixed number, not a fraction.** On a batch of
twelve, one forgiven item is eight percent; on a batch of two it is half. The
allowance was kept absolute because the failure it guards against — a genuine
boundary case — does not scale with batch size, but a large batch with several
boundary items will fail consensus rather than settle.

**None of them tell you the criterion was good.** Every contract reports how
often it refused, and a high refusal rate is a statement about the criterion
rather than about the network. Reading that signal is left to the caller.

**Consensus here is on structure, so two nodes can agree on a structure derived
from different reasoning.** The `why` strings are leader-supplied, excluded from
consensus, sanitised on the way into storage, and every view that returns them
says so. Nothing in any contract acts on them.
