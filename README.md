<div align="center">

<img src="brand/lockup.svg" alt="bracket" height="72">

**When you cannot agree on the score, agree on the shape.**

Four GenLayer Intelligent Contract primitives for judgments that come in sets,
where what crosses consensus is the structure of a decision and never the
number behind it.

[![Built by InferNode](https://img.shields.io/badge/built%20by-InferNode-E0A23C?style=flat-square)](https://x.com/Infer_node)
[![GenLayer](https://img.shields.io/badge/GenLayer-Intelligent%20Contracts-0C0D10?style=flat-square)](https://genlayer.com)
[![Live on studionet](https://img.shields.io/badge/studionet-4%20live-1F7A4D?style=flat-square)](#it-is-live-and-every-refusal-is-on-chain-too)
[![License MIT](https://img.shields.io/badge/license-MIT-232830?style=flat-square)](LICENSE)

</div>

---

## The name

A bracket is two things at once, and this family is both of them. It is the band
you group into — a tax bracket, a scoring bracket, everything inside it treated
as the same. And it is the structure you rank with. Every contract here groups
what it cannot separate rather than pretending to separate it, then publishes the
grouping instead of the numbers.

The mark is four bars with a bracket closing around all four. Each contract
carries the same geometry with its own answer inside it.

## Overview

Two validators will never agree that a thing scores 7.3 rather than 7.6. They
will agree, easily and repeatedly, that it beats the thing next to it.

That is the whole observation. A raw score does not survive the next request, but
an ordering does. A top-five list does. A three-way triage does. So every contract
here takes a fine-grained judgment and collapses it into a coarser structure
**before** consensus ever sees it. The structure crosses the boundary; the numbers
behind it are discarded.

> **The one idea worth stealing.** Do not ask the network to agree on a
> measurement. Ask it to agree on a **structure**, and derive the structure
> deterministically from the measurement. The coarser the structure, the more
> reliably consensus settles — so choose the coarsest structure your application
> can actually use.

## Reviewer links

Everything a reviewer needs, in the order it is useful.

| | |
|---|---|
| **Verify in two minutes** | `pip install pytest && pytest tests/ -q` — no Studio, no network, no API key |
| **Flagship 1** | [`contracts/tiebreak.py`](contracts/tiebreak.py) — the atom the other three call |
| **Flagship 2** | [`contracts/slate.py`](contracts/slate.py) — the ordering, with the ties left in |
| **The other two** | [`contracts/cutline.py`](contracts/cutline.py) · [`contracts/winnow.py`](contracts/winnow.py) |
| **Agreement rules alone** | [`lib/bracket_consensus.py`](lib/bracket_consensus.py) — pure, no storage, no model |
| **Specification** | [CONTRACTS.md](CONTRACTS.md) — purpose, consensus, state, API, reuse, per contract |
| **Decisions and limits** | [DECISIONS.md](DECISIONS.md) — every bug found, with the error it produced, and what each contract cannot do |
| **Live on chain** | [four addresses, eight outcomes](#it-is-live-and-every-refusal-is-on-chain-too) |
| **Tests** | [`tests/`](tests/) — pure rules, static shape, end-to-end, integration |

---

## It is live, and every refusal is on chain too

Four contracts, eight outcomes. Each one resolved once and refused once, because
a page showing only successes proves the file compiles and nothing else — and
refusing is what these primitives are for.

| Contract | Address | Resolved | Refused |
|---|---|---|---|
| **Tiebreak** | [`0x9fE538dC…8d6F4667Fe40C4`](https://explorer-studio.genlayer.com/address/0x9fE538dC6e05b8316Cd9E9FE7a6bBF4667Fe40C4) | `verdict(0)` → `a` | `verdict(1)` → `tied`, `tied_pct` `100.0` |
| **Slate** | [`0x222CD021…aA13A67C9`](https://explorer-studio.genlayer.com/address/0x222CD02132a4f158E3C67E8D0757b88aA13A67C9) | `order(0)` → `0:1\|1:2\|2:3\|3:4` | `order(1)` → `0:1\|1:1\|2:1\|3:1`, `undifferentiated` |
| **Cutline** | [`0xC4ee53aD…2e2d35b2bB`](https://explorer-studio.genlayer.com/address/0xC4ee53aDfb9569150C7cCfA79590422e2d35b2bB) | `selected(0)` → `0\|1` | `selected(1)` → `""`, `cut_is_arbitrary` |
| **Winnow** | [`0x4D75f5a5…0217E81f`](https://explorer-studio.genlayer.com/address/0x4D75f5a5505c442f6a781dc05828E0220217E81f) | `accept\|review\|reject\|accept` | `standard_too_vague` |

Every refusal above came from the **same input** as the success beside it, with
one parameter changed. Slate ranked four proposals cleanly at `closeness 8.0`
and collapsed all four into one band at `1000`. Cutline selected two at `8.0`
and refused to cut at all at `1000`, because the line then fell inside a tie.
Winnow triaged the same four items twice and marked the second run
`standard_too_vague` when the standard was written vaguely and the review
ceiling was zero.

Cutline stored its own reason for refusing:

> Item 0 provides precise numerical data, while others rely on subjective
> feelings or vague marketing language.

The model saw the difference. The contract still declined to draw the line,
because the line fell inside a band it had already said it would not split.

---

## The ladder

Four contracts, in decreasing precision. Each rung asks less of the network than
the one above it, and each is the right answer for a different application.

| Contract | What crosses consensus | What is deliberately discarded |
|---|---|---|
| [**Slate**](contracts/slate.py) | the ordering, with ties banded | the scores |
| [**Cutline**](contracts/cutline.py) | set membership of the top K | the order inside the set |
| [**Winnow**](contracts/winnow.py) | which bucket each item is in | any ordering at all |
| [**Tiebreak**](contracts/tiebreak.py) | whether two items differ at all | by how much |

**Tiebreak is the atom.** The three above it call the same question internally:
*is this difference real, or is it noise?* Slate uses it to decide which items
share a rank, Cutline to decide whether the cut falls inside a tie, Winnow to
decide whether an item belongs in the uncertain middle.

One primitive, three compositions.

---

## Flagship 1 · Tiebreak — is this difference real?

Decide whether two items are distinguishable under a written criterion, or
whether any ordering between them would be noise.

**The failure it catches: position bias.** Language models systematically favour
whichever option appears first. Ask "which is better, A or B?" and a
position-biased model says A. Ask "which is better, B or A?" and it says B. It
has expressed a preference about presentation order, not about the items.

**Validator consensus does not catch this.** Every validator builds the prompt
from the same template, so every validator presents the items in the same order,
inherits the same bias, and they all agree. The network converges confidently on
an artefact of the prompt.

Two prompts run sequentially in one block — A first, then B first — and only two
of the nine combinations survive both presentations:

```python
def combine_rounds(forward, reverse):
    f, r = normalise_side(forward), normalise_side(reverse)
    if f == A and r == A:
        return A            # A won whether shown first or second
    if f == B and r == B:
        return B
    return TIED             # the answer moved when the order moved
```

The validator has two layers, and the first is worth lifting into other
contracts:

```python
# LAYER 1 — internal honesty, and it costs nothing.
#   combine_rounds is pure, so a validator confirms the leader's own two rounds
#   produce the verdict it reported WITHOUT running a single prompt.
if combine_rounds(side["forward"], side["reverse"]) != side["verdict"]:
    return False

# LAYER 2 — agreement on the verdict, never on the raw rounds.
#   Two honest nodes may differ on one round and still land on the same verdict.
return mine["verdict"] == theirs["verdict"]
```

`TIED` is not a failure. It is the network agreeing, precisely, that the
criterion does not separate these two.

## Flagship 2 · Slate — an ordering, with the ties left in

Order N items against a criterion, collapsing items that cannot be told apart
into a shared rank. The output is not a list: it is rank 1, rank 2, rank 2,
rank 4.

Comparing the raw ordering with `strict_eq` never settles — two honest
validators swap two adjacent near-equal items roughly every time. Loosening to a
prompt-based principle accepts an ordering that reversed the top two, which is
the only part anyone cares about. So the block returns an order and a score per
item, and the **contract** bands them:

```python
def band_scores(scores, closeness):
    # Adjacent scores within `closeness` share a band, transitively along the
    # run: if a is close to b and b is close to c, all three share a band.
    bands, current = [], 1
    for i, s in enumerate(scores):
        if i > 0 and abs(scores[i - 1] - s) > closeness:
            current += 1
        bands.append(current)
    return bands
```

Consensus is `strict_eq` on the canonical string, and on nothing else:

```
"2:1|0:2|1:2|3:3"      items 0 and 1 are tied at rank 2
```

Item indices are sorted **within** each band. Between bands the order is the
whole answer; inside a band the contract has already said it will not separate
them, so the order there must not decide whether consensus settles.

**The move being demonstrated:** canonicalise, then use the cheapest principle.
Most contracts reach for a looser equivalence principle when strict equality
fails. The better instinct is to ask what noise is causing the failure, remove it
deterministically, and keep strict equality.

## Cutline — the best K of N

Select the best K against a criterion. Consensus is on set membership only:
`"0|3|7"` — who is in, not who is first. The same lever as Slate, pulled harder,
because for a grant round or a shortlist the only fact anyone acts on is who got
in.

If item K and item K+1 are indistinguishable the cut is arbitrary, and a
selection that looks authoritative is worse than a refusal. What happens then is
declared at registration:

```python
def cut_at(bands, k, on_tie):
    if bands[k - 1] != bands[k]:
        return k, False           # clean boundary between two bands
    if on_tie == REFUSE:
        return 0, True            # a hard budget: select nobody, say why
    n = k                          # a target: expand through the tied band
    while n < len(bands) and bands[n] == bands[k - 1]:
        n += 1
    return n, False
```

Neither policy is right in general, which is exactly why it is a parameter. A
contract that silently picked one would be making a governance decision on the
caller's behalf.

## Winnow — accept, reject, review

Sort a batch into three buckets against a written standard. No ordering at all —
the coarsest rung, and the one most workflows actually want, because they need
to know what to act on, what to discard, and what a human has to look at.

The agreement rule has one deliberate allowance, and it is the heart of the
design:

```python
def partition_agrees(mine, theirs, n):
    drifted = 0
    for i in range(n):
        if mine[i] == theirs[i]:
            continue
        if REVIEW not in (mine[i], theirs[i]):
            return False          # accept <-> reject, never forgiven
        drifted += 1
        if drifted > 1:           # one boundary item, not two
            return False
    return True
```

An allowance that forgave *any* single difference would let two nodes disagree
about whether an item passes or fails and still settle — the worst possible
outcome, because the record would look decisive. Routing it through `review`
means the only forgiven disagreement is one about certainty, never one about
direction.

---

## Refusing is designed

| Contract | Refusal | What it means |
|---|---|---|
| Tiebreak | `tied` | the criterion does not separate these two items |
| Slate | `undifferentiated` | every item landed in one band |
| Cutline | `cut_is_arbitrary` | the cut fell inside a tie, and the policy was refuse |
| Winnow | `standard_too_vague` | more of the batch went to review than was tolerable |

Each is stored and exposed, not raised. A slate where everything ties is not a
broken run, it is a finding.

---

## Running the tests

```bash
pip install pytest
pytest tests/ -q
```

<!-- measured:tests -->
`pytest tests/ -q` reports **452 passed, 1 skipped**, and every one of the **58** mutations below is caught.
<!-- /measured:tests -->

Nothing else is needed: no Studio, no network, no API key. A reviewer with two
minutes can verify every claim on this page.

**`tests/test_logic.py`** — the agreement rules, exhaustively. Each rule is a
pure module-level function inside its contract, and this file reads the **real
contract source** and executes it. There is no second copy to drift out of sync.

**`tests/test_e2e.py`** — the contracts, executed on
[`tests/glsim.py`](tests/glsim.py), a GenVM stand-in shipped here. The critical
property is that the leader and the validator get their **own** mock answers:

```python
self.mocks(CLEAN, v_prompts=SWAPPED)   # the validator saw a different round
```

Every mocking framework feeds both nodes the same data by default, which is
exactly why a contract that quietly assumes both nodes see identical bytes
passes its suite and then fails on a real network.

The same file holds the **static shape tests** — a pinned runner header, no
collection inside a storage dataclass, no field or method declared twice, no
block closing over storage, a flat dict of `str` at every block boundary. They
are not tests of behaviour; each one corresponds to a GenVM failure that
behaviour tests cannot see, because the contract works perfectly on a
workstation and then fails at deploy or returns `Result Code <unknown>` with no
traceback at all.

**`tests/test_integration.py`** — against a real Studio, skipped automatically
when `genlayer-test` is absent.

### The tests have teeth

Every safety property was broken on purpose to confirm a test notices. The table
is generated by `python scripts/mutate.py`, which applies each mutation to a
scratch copy and records which test caught it.

<!-- measured:mutations -->
| Mutation | Caught by |
|---|---|
| the internal-honesty layer removed | `test_a_liar_is_rejected_even_when_the_verdicts_match` |
| a position-biased result treated as separable | `test_a_model_that_names_whichever_item_it_saw_first_is_caught` |
| an unknown answer mapped onto a side instead of neither | `test_an_unreadable_round_produces_tied_never_a_winner` |
| the honesty layer removed and the verdict then trusted | `test_a_liar_is_rejected_even_when_the_verdicts_match` |
| the criterion length bound removed | `test_a_short_criterion_is_refused` |
| the item length cap removed | `test_an_over_long_item_is_refused` |
| a tie counted as a win for a | `test_stability_accumulates_across_comparisons` |
| count() reporting comparisons rather than registered pairs | `test_count_reflects_registrations` |
| the two prompts made asymmetric | `test_the_two_prompts_differ_only_in_the_order_of_the_items` |
| agreement compared on the raw rounds instead of the verdict | `test_two_honest_nodes_differing_on_one_round_still_settle` |
| the reason sanitiser disabled | `test_a_leader_supplied_reason_is_sanitised_before_storage` |
| control characters left in stored reasons | `test_a_leader_supplied_reason_is_sanitised_before_storage` |
| the view bounds check removed | `test_every_view_bounds_checks_through_a_guarded_lookup` |
| negative ids allowed through to Python list indexing | `test_every_view_bounds_checks_through_a_guarded_lookup` |
| a lookup that ignores the parent id | `test_two_pairs_do_not_read_each_other_s_comparisons` |
| a nested mapping returned from the block | `test_the_block_boundary_carries_flat_strings_only` |
| a bool returned from the block | `test_a_wins_when_it_wins_in_both_orders` |
| a collection nested back into a storage dataclass | `test_no_storage_dataclass_holds_a_collection` |
| a storage field declared twice | `test_no_storage_field_is_declared_twice` |
| two identical items accepted as a comparable pair | `test_two_identical_items_are_refused` |
| banding disabled, the raw order compared | `test_items_within_the_closeness_threshold_share_a_rank` |
| the closeness threshold widened tenfold | `test_a_clean_ranking_is_stored_in_rank_order` |
| banding measured from the head of the run instead of the neighbour | `test_items_within_the_closeness_threshold_share_a_rank` |
| the order inside a band left to decide consensus | `test_two_nodes_swapping_a_tied_adjacent_pair_still_settle` |
| a non-permutation accepted as an order | `test_a_leader_returning_a_non_permutation_is_rejected` |
| a repeated index accepted by the permutation check | `test_a_leader_returning_a_non_permutation_is_rejected` |
| the undifferentiated refusal removed | `test_a_slate_where_everything_ties_is_a_finding_not_a_failure` |
| a non-finite score accepted into banding | `test_a_non_finite_score_is_rejected` |
| the score count no longer required to match the item count | `test_a_leader_returning_the_wrong_number_of_scores_is_rejected` |
| the view bounds check removed | `test_a_nonexistent_or_negative_id_is_a_user_error` |
| negative ids allowed through to Python list indexing | `test_a_nonexistent_or_negative_id_is_a_user_error` |
| a lookup that ignores the parent id | `test_two_slates_do_not_read_each_other_s_rankings` |
| duplicate items accepted onto one slate | `test_duplicate_items_are_refused` |
| a list returned across the block boundary | `test_a_clean_ranking_is_stored_in_rank_order` |
| selection compared as ordered rather than sorted | `test_a_clean_boundary_selects_exactly_k` |
| the boundary tie check removed | `test_refuse_selects_nobody_when_the_cut_falls_inside_a_tie` |
| on_tie ignored, always expand | `test_refuse_selects_nobody_when_the_cut_falls_inside_a_tie` |
| on_tie ignored, always refuse | `test_expand_takes_the_whole_tied_band` |
| expand stopping after the first tied item | `test_expand_runs_to_the_end_of_a_trailing_tie` |
| k no longer required to be inside the item count | `test_a_k_outside_the_item_count_is_refused` |
| an unknown tie policy accepted | `test_an_unknown_tie_policy_is_refused` |
| the view bounds check removed | `test_a_nonexistent_or_negative_id_is_a_user_error` |
| negative ids allowed through to Python list indexing | `test_a_nonexistent_or_negative_id_is_a_user_error` |
| a lookup that ignores the parent id | `test_two_cutlines_do_not_read_each_other_s_selections` |
| a non-permutation accepted as an order | `test_a_leader_returning_a_non_permutation_is_rejected` |
| banding disabled before the cut | `test_refuse_selects_nobody_when_the_cut_falls_inside_a_tie` |
| the one-item allowance widened to two | `test_two_items_drifting_does_not_settle` |
| accept-to-reject drift forgiven | `test_an_item_flipping_accept_to_reject_never_settles` |
| the allowance no longer routed through review | `test_an_item_flipping_accept_to_reject_never_settles` |
| the max_review refusal removed | `test_a_batch_mostly_in_review_is_marked_too_vague` |
| the vagueness threshold made inclusive | `test_exactly_at_the_threshold_is_allowed` |
| an unrecognised label mapped onto accept instead of review | `test_a_partition_is_stored_in_item_order` |
| the length check removed from the agreement rule | `test_a_length_mismatch_is_refused` |
| the view bounds check removed | `test_a_nonexistent_or_negative_id_is_a_user_error` |
| negative ids allowed through to Python list indexing | `test_a_nonexistent_or_negative_id_is_a_user_error` |
| the per-item index no longer bounds-checked | `test_a_negative_item_index_is_refused` |
| a lookup that ignores the parent id | `test_two_batches_do_not_read_each_other_s_triages` |
| the review percentage bound removed | `test_a_percentage_outside_zero_to_a_hundred_is_refused` |
<!-- /measured:mutations -->

Three mutations escaped during the build. One was a genuine gap — a guard with
no test of its own — and two were defences that a defence in front of them had
already made unobservable, leaving tests that *could not fail*.
[DECISIONS.md](DECISIONS.md) records what happened to each, because a test that
cannot fail is worse than no test.

---

## Repository layout

```
bracket/
├── contracts/
│   ├── tiebreak.py          the atom: one comparison, both presentation orders
│   ├── slate.py             an ordering, with the ties banded
│   ├── cutline.py           the top K, membership only
│   └── winnow.py            accept / reject / review
├── lib/
│   └── bracket_consensus.py the agreement rules alone, pure and copyable
├── tests/
│   ├── glsim.py             a GenVM stand-in with independent leader and validator worlds
│   ├── test_logic.py        the pure rules, executed out of the real contract source
│   ├── test_e2e.py          the contracts executed, plus the static shape tests
│   └── test_integration.py  against a real Studio, skipped when gltest is absent
├── scripts/
│   ├── deploy.sh            lints, deploys, and exercises each contract
│   ├── mutate.py            breaks every safety property on purpose
│   └── measure.py           writes the measured counts into this file
├── brand/
│   ├── mark.svg  lockup.svg  social.svg  social.png  BRAND.md
│   └── family/              one mark per contract, same geometry
├── README.md  CONTRACTS.md  DECISIONS.md  SUBMISSION.md  LICENSE
└── conftest.py  pytest.ini  requirements-dev.txt  gltest.config.yaml
```

Four contracts, one shape. Every collection is a top level contract field and
child records carry a parent id, because a storage dataclass cannot hold a
collection. Every public parameter is `str`, `u256` or `bool`; collections
arrive pipe-joined. Every block returns a flat dict of `str`. Every view
bounds-checks its id and rejects negatives explicitly. Every `raise` is
`gl.vm.UserError`. [CONTRACTS.md](CONTRACTS.md) has the per-contract detail and
[DECISIONS.md](DECISIONS.md) says what each rule cost to learn.

---

## Deploying

Deployment is done by hand through the Studio web interface at
[studio.genlayer.com](https://studio.genlayer.com): paste the contract, deploy,
and call the methods through the form. No private key ever goes into a file or a
tool. [`scripts/deploy.sh`](scripts/deploy.sh) is the CLI equivalent for anyone
who prefers it.

For each contract, run one call that succeeds and one that refuses. A contract
page showing only successes is a weaker demonstration than one showing the
primitive decline to answer — and refusing is what these primitives are for.

---

## Why this is not a thin LLM wrapper

In all four contracts the model produces a comparison or a score, and never the
outcome. The outcome comes from a pure function in the deterministic half,
against rules frozen on chain before the model ran. Swap in a worse model and
the mechanism still works — it just refuses more often, which is the correct
response to a worse model.

## Related work

[**Crosscheck**](https://github.com/meitipro/genlayer-crosscheck) asks one
yes/no question twice in opposite framings and refuses when the framings
disagree. Tiebreak applies that same insight to a different axis: instead of
varying the framing of a question about one item, it varies the **order** of two
items. The borrowed idea is named on purpose — it turns two submissions into a
body of work rather than two unrelated files.

[**Tolerance**](https://github.com/meitipro/genlayer-tolerance) makes numeric
agreement a per-field on-chain declaration. Where Slate discards the numbers and
keeps the shape, Tolerance keeps the numbers and declares how far apart two
nodes may be about each one.

---

Published by [InferNode](https://x.com/Infer_node).
