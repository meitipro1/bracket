"""Mutation pass: break every safety property on purpose, confirm a test notices.

Passing tests prove nothing on their own. Each entry below is a one-line edit to
a contract that removes a defence. The suite must fail for every one of them, and
this script records WHICH test caught it so the table in the README is measured
rather than claimed.

    python scripts/mutate.py            # run them all, print the table
    python scripts/mutate.py --md       # emit the markdown table for the README

An escaping mutation is a finding, not a nuisance. It means either a missing
test, or a later defence strict enough to cover a case an earlier test was
supposed to catch -- which leaves that earlier test unable to fail. A test that
cannot fail is worse than no test, because it reports coverage it does not
provide.
"""

import argparse
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (contract, label, find, replace)
MUTATIONS = [
    # -- tiebreak ----------------------------------------------------------
    (
        "tiebreak.py",
        "the internal-honesty layer removed",
        "        if combine_rounds(side.get(\"forward\", \"\"), side.get(\"reverse\", \"\")) != v:\n            return False\n",
        "",
    ),
    (
        "tiebreak.py",
        "a position-biased result treated as separable",
        "    if f == A and r == A:\n        return A\n    if f == B and r == B:\n        return B\n    return TIED",
        "    if f == A:\n        return A\n    if f == B:\n        return B\n    return TIED",
    ),
    (
        "tiebreak.py",
        "an unknown answer mapped onto a side instead of neither",
        "    return NEITHER\n\n\ndef combine_rounds",
        "    return A\n\n\ndef combine_rounds",
    ),
    (
        "tiebreak.py",
        # Coupled on purpose. Trusting the leader's verdict ALONE is not
        # observable, because layer 1 already proves it equals the
        # recomputation -- see DECISIONS.md, "a mutation that could not be
        # caught". Removing both defences at once is what a real attacker
        # would have to do, and that is catchable.
        "the honesty layer removed and the verdict then trusted",
        (
            ("        if combine_rounds(side.get(\"forward\", \"\"), side.get(\"reverse\", \"\")) != v:\n            return False\n", ""),
            ("        verdict = combine_rounds(forward, reverse)", "        verdict = str(res.get(\"verdict\", \"\"))"),
        ),
        None,
    ),
    (
        "tiebreak.py",
        "the criterion length bound removed",
        "        if len(c) < CRITERION_MIN or len(c) > CRITERION_MAX:\n            raise gl.vm.UserError(\"criterion must be 12 to 300 characters\")\n",
        "",
    ),
    (
        "tiebreak.py",
        "the item length cap removed",
        "        if len(a) > ITEM_MAX or len(b) > ITEM_MAX:\n            raise gl.vm.UserError(\"an item may be at most 600 characters\")\n",
        "",
    ),
    (
        "tiebreak.py",
        "a tie counted as a win for a",
        "        else:\n            q.n_tied = u256(int(q.n_tied) + 1)",
        "        else:\n            q.n_a = u256(int(q.n_a) + 1)",
    ),
    (
        "tiebreak.py",
        "count() reporting comparisons rather than registered pairs",
        "        return u256(len(self.pairs))",
        "        return u256(len(self.comparisons))",
    ),
    (
        "tiebreak.py",
        "the two prompts made asymmetric",
        "        \"Which item better meets the criterion?\\n\"",
        "        \"Which item better meets the criterion? \" + first_label + \"?\\n\"",
    ),
    (
        "tiebreak.py",
        "agreement compared on the raw rounds instead of the verdict",
        "    return str(mine.get(\"verdict\", \"\")) == str(theirs.get(\"verdict\", \"\"))",
        "    return (str(mine.get(\"forward\", \"\")) == str(theirs.get(\"forward\", \"\"))\n            and str(mine.get(\"reverse\", \"\")) == str(theirs.get(\"reverse\", \"\")))",
    ),
    (
        "tiebreak.py",
        "the reason sanitiser disabled",
        "        if ch in MARKUP:\n            continue\n",
        "",
    ),
    (
        "tiebreak.py",
        "control characters left in stored reasons",
        "        if ord(ch) < 32 or ord(ch) == 127:\n            out.append(\" \")\n        else:\n            out.append(ch)",
        "        out.append(ch)",
    ),
    (
        "tiebreak.py",
        "the view bounds check removed",
        "        if i < 0 or i >= len(self.pairs):\n            raise gl.vm.UserError(\"no such pair\")\n",
        "",
    ),
    (
        "tiebreak.py",
        "negative ids allowed through to Python list indexing",
        "        if i < 0 or i >= len(self.pairs):",
        "        if i >= len(self.pairs):",
    ),
    (
        "tiebreak.py",
        "a lookup that ignores the parent id",
        "            if int(self.comparisons[k].pair_id) == pair_id:\n                return k",
        "            return k",
    ),
    (
        "tiebreak.py",
        "a nested mapping returned from the block",
        "                \"why_forward\": sanitise_reason(forward_raw.get(\"why\", \"\")),\n                \"why_reverse\": sanitise_reason(reverse_raw.get(\"why\", \"\")),",
        "                \"why\": {\"forward\": sanitise_reason(forward_raw.get(\"why\", \"\")),\n                        \"reverse\": sanitise_reason(reverse_raw.get(\"why\", \"\"))},",
    ),
    (
        "tiebreak.py",
        "a bool returned from the block",
        "                \"verdict\": combine_rounds(f, r),",
        "                \"verdict\": combine_rounds(f, r),\n                \"tied\": combine_rounds(f, r) == TIED,",
    ),
    (
        "tiebreak.py",
        "a collection nested back into a storage dataclass",
        "@allow_storage\n@dataclass\nclass Pair:\n    author: Address",
        "@allow_storage\n@dataclass\nclass Pair:\n    rounds: DynArray[str]\n    author: Address",
    ),
    (
        "tiebreak.py",
        "a storage field declared twice",
        "    pairs: DynArray[Pair]\n    comparisons: DynArray[Comparison]",
        "    pairs: DynArray[Pair]\n    comparisons: DynArray[Comparison]\n    comparisons: DynArray[Comparison]",
    ),
    (
        "tiebreak.py",
        "two identical items accepted as a comparable pair",
        "        if a == b:\n            raise gl.vm.UserError(\"the two items are identical\")\n",
        "",
    ),

    # -- slate -------------------------------------------------------------
    (
        "slate.py",
        "banding disabled, the raw order compared",
        "        if i > 0 and abs(scores[i - 1] - scores[i]) > closeness:\n            current += 1",
        "        if i > 0:\n            current += 1",
    ),
    (
        "slate.py",
        "the closeness threshold widened tenfold",
        "        if i > 0 and abs(scores[i - 1] - scores[i]) > closeness:",
        "        if i > 0 and abs(scores[i - 1] - scores[i]) > closeness * 10:",
    ),
    (
        "slate.py",
        "banding measured from the head of the run instead of the neighbour",
        "abs(scores[i - 1] - scores[i]) > closeness",
        "abs(scores[0] - scores[i]) > closeness",
    ),
    (
        "slate.py",
        "the order inside a band left to decide consensus",
        "        for idx in sorted(order[i:j]):\n            out.append(str(idx) + \":\" + str(bands[i]))",
        "        for idx in order[i:j]:\n            out.append(str(idx) + \":\" + str(bands[i]))",
    ),
    (
        "slate.py",
        "a non-permutation accepted as an order",
        "    if not is_permutation(out, n):\n        return None\n    return out",
        "    return out",
    ),
    (
        "slate.py",
        "a repeated index accepted by the permutation check",
        "        if i < 0 or i >= n or i in seen:\n            return False",
        "        if i < 0 or i >= n:\n            return False",
    ),
    (
        "slate.py",
        "the undifferentiated refusal removed",
        "        refusal = UNDIFFERENTIATED if is_undifferentiated(bands) else \"\"",
        "        refusal = \"\"",
    ),
    (
        "slate.py",
        "a non-finite score accepted into banding",
        "        if v != v or v == INF or v == -INF:\n            return None\n        out.append(v)",
        "        out.append(v)",
    ),
    (
        "slate.py",
        "the score count no longer required to match the item count",
        "    parts = str(text).split(\"|\")\n    if len(parts) != n:\n        return None\n    out = []\n    for p in parts:\n        try:\n            v = float(p)",
        "    parts = str(text).split(\"|\")\n    out = []\n    for p in parts:\n        try:\n            v = float(p)",
    ),
    (
        "slate.py",
        "the view bounds check removed",
        "        if i < 0 or i >= len(self.slates):\n            raise gl.vm.UserError(\"no such slate\")\n",
        "",
    ),
    (
        "slate.py",
        "negative ids allowed through to Python list indexing",
        "        if i < 0 or i >= len(self.slates):",
        "        if i >= len(self.slates):",
    ),
    (
        "slate.py",
        "a lookup that ignores the parent id",
        "            if int(r.slate_id) == slate_id:\n                return k",
        "            return k",
    ),
    (
        "slate.py",
        "duplicate items accepted onto one slate",
        "        if len(set(parts)) != len(parts):\n            raise gl.vm.UserError(\"items must be distinct\")\n",
        "",
    ),
    (
        "slate.py",
        "a list returned across the block boundary",
        "                \"order\": join_ints(order) if isinstance(order, list) else str(order),",
        "                \"order\": order if isinstance(order, list) else str(order),",
    ),

    # -- cutline -----------------------------------------------------------
    (
        "cutline.py",
        "selection compared as ordered rather than sorted",
        "    return \"|\".join(str(i) for i in sorted(selected))",
        "    return \"|\".join(str(i) for i in selected)",
    ),
    (
        "cutline.py",
        "the boundary tie check removed",
        "    if bands[k - 1] != bands[k]:\n        return k, False           # clean boundary between two bands",
        "    return k, False",
    ),
    (
        "cutline.py",
        "on_tie ignored, always expand",
        "    if on_tie == REFUSE:\n        return 0, True",
        "    if False:\n        return 0, True",
    ),
    (
        "cutline.py",
        "on_tie ignored, always refuse",
        "    if on_tie == REFUSE:\n        return 0, True",
        "    if True:\n        return 0, True",
    ),
    (
        "cutline.py",
        "expand stopping after the first tied item",
        "    while n < len(bands) and bands[n] == bands[k - 1]:\n        n += 1",
        "    if n < len(bands) and bands[n] == bands[k - 1]:\n        n += 1",
    ),
    # NOT listed: "the arbitrary flag left out of the agreement rule". Under
    # `refuse` an arbitrary cut selects nobody, so the flag is derivable from
    # the canonical string; under `expand` it is always False. Removing the
    # conjunct changes no outcome, so no test can catch it and claiming one
    # would be a lie. Kept in the contract as defence in depth. See
    # DECISIONS.md, "two mutations that could not be caught".
    (
        "cutline.py",
        "k no longer required to be inside the item count",
        "        if kk < 1 or kk >= len(parts):\n            raise gl.vm.UserError(\"k must be at least 1 and fewer than the items\")\n",
        "",
    ),
    (
        "cutline.py",
        "an unknown tie policy accepted",
        "        if policy not in ON_TIE:\n            raise gl.vm.UserError(\"on_tie must be refuse or expand\")\n",
        "",
    ),
    (
        "cutline.py",
        "the view bounds check removed",
        "        if i < 0 or i >= len(self.cutlines):\n            raise gl.vm.UserError(\"no such cutline\")\n",
        "",
    ),
    (
        "cutline.py",
        "negative ids allowed through to Python list indexing",
        "        if i < 0 or i >= len(self.cutlines):",
        "        if i >= len(self.cutlines):",
    ),
    (
        "cutline.py",
        "a lookup that ignores the parent id",
        "            if int(s.cutline_id) == cutline_id:\n                return j",
        "            return j",
    ),
    (
        "cutline.py",
        "a non-permutation accepted as an order",
        "    if not is_permutation(out, n):\n        return None\n    return out",
        "    return out",
    ),
    (
        "cutline.py",
        "banding disabled before the cut",
        "        if i > 0 and abs(scores[i - 1] - scores[i]) > closeness:\n            current += 1",
        "        if i > 0:\n            current += 1",
    ),

    # -- winnow ------------------------------------------------------------
    (
        "winnow.py",
        "the one-item allowance widened to two",
        "        if drifted > 1:               # one boundary item, not two\n            return False",
        "        if drifted > 2:\n            return False",
    ),
    (
        "winnow.py",
        "accept-to-reject drift forgiven",
        "        if REVIEW not in (mine[i], theirs[i]):\n            return False              # accept <-> reject, never forgiven",
        "        if False:\n            return False",
    ),
    (
        "winnow.py",
        "the allowance no longer routed through review",
        "        if REVIEW not in (mine[i], theirs[i]):",
        "        if REVIEW in (mine[i], theirs[i]) and False:",
    ),
    (
        "winnow.py",
        "the max_review refusal removed",
        "        refusal = TOO_VAGUE if is_too_vague(partition, max_pct) else \"\"",
        "        refusal = \"\"",
    ),
    (
        "winnow.py",
        "the vagueness threshold made inclusive",
        "    return review_count(partition) * 100 > int(max_review_pct) * n",
        "    return review_count(partition) * 100 >= int(max_review_pct) * n",
    ),
    (
        "winnow.py",
        "an unrecognised label mapped onto accept instead of review",
        "    return REVIEW\n\n\ndef parse_partition",
        "    return ACCEPT\n\n\ndef parse_partition",
    ),
    (
        "winnow.py",
        "the length check removed from the agreement rule",
        "    if len(mine) != n or len(theirs) != n:\n        return False\n    drifted = 0",
        "    drifted = 0",
    ),
    # NOT listed: "the bucket count no longer required to match the item count"
    # inside parse_partition. partition_agrees length-checks first and rejects
    # the run before the parse guard can matter, so removing it changes no
    # outcome. The BEHAVIOUR is covered -- a leader labelling the wrong number
    # of items is refused, and that test exists -- but the guard itself is
    # defence in depth. See DECISIONS.md.
    (
        "winnow.py",
        "the view bounds check removed",
        "        if i < 0 or i >= len(self.batches):\n            raise gl.vm.UserError(\"no such batch\")\n",
        "",
    ),
    (
        "winnow.py",
        "negative ids allowed through to Python list indexing",
        "        if i < 0 or i >= len(self.batches):",
        "        if i >= len(self.batches):",
    ),
    (
        "winnow.py",
        "the per-item index no longer bounds-checked",
        "        if i < 0 or i >= int(b.n_items):\n            raise gl.vm.UserError(\"no such item\")\n",
        "",
    ),
    (
        "winnow.py",
        "a lookup that ignores the parent id",
        "            if int(t.batch_id) == batch_id:\n                return j",
        "            return j",
    ),
    (
        "winnow.py",
        "the review percentage bound removed",
        "        if pct < 0 or pct > 100:\n            raise gl.vm.UserError(\"max_review_pct must be 0 to 100\")\n",
        "",
    ),
]


def run_one(contract, label, find, replace):
    """Apply one mutation into a scratch copy and report the first test to fail."""
    with tempfile.TemporaryDirectory() as tmp:
        dst = pathlib.Path(tmp) / "repo"
        shutil.copytree(
            ROOT, dst,
            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".git",
                                          "artifacts", "*.pyc"),
        )
        target = dst / "contracts" / contract
        src = target.read_text(encoding="utf-8")
        # A mutation is usually one edit. A few need two at once, because a
        # single defence is only observable when the one behind it is gone too.
        edits = find if isinstance(find, tuple) else ((find, replace),)
        for f, r in edits:
            if f not in src:
                return "PATTERN NOT FOUND", None
            src = src.replace(f, r, 1)
        target.write_text(src, encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-x", "-q",
             "--no-header", "-p", "no:cacheprovider"],
            cwd=dst, capture_output=True, text=True,
        )
        if proc.returncode == 0:
            return "ESCAPED", None

        out = proc.stdout + proc.stderr
        # Collection errors count as caught: an import that dies is a contract
        # that would not deploy.
        m = re.search(r"^(?:FAILED|ERROR) (\S+?)::(\S+?)(?:\[|\s|$)", out, re.M)
        if m:
            return "caught", m.group(2).split("::")[-1]
        m = re.search(r"^E\s+(\w*(?:Error|Exception))", out, re.M)
        if m:
            return "caught", m.group(1) + " at import"
        return "caught", "unnamed failure"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", action="store_true", help="emit the README table")
    args = ap.parse_args()

    rows, escaped = [], []
    for contract, label, find, replace in MUTATIONS:
        status, test = run_one(contract, label, find, replace)
        if status == "caught":
            rows.append((contract, label, test))
            if not args.md:
                print("  caught   %-52s %s" % (label, test))
        else:
            escaped.append((contract, label, status))
            print("  %-8s %s" % (status, label), file=sys.stderr)

    if args.md:
        print("| Mutation | Caught by |")
        print("|---|---|")
        for _c, label, test in rows:
            print("| %s | `%s` |" % (label, test))
    else:
        print()
        print("  %d mutations, %d caught, %d escaped"
              % (len(MUTATIONS), len(rows), len(escaped)))

    return 1 if escaped else 0


if __name__ == "__main__":
    sys.exit(main())
