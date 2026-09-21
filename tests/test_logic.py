"""The agreement rules, exhaustively, executed out of the real contract files.

A contract file cannot simply be imported: it opens with the dependency header
and does `from genlayer import *`. So this file reads the source, cuts out the
section between the PURE RULES markers, and executes that. Those helpers are
dependency free by design, so they need no stub at all.

The alternative -- copying the rules into the test file -- creates a second copy
that drifts, and a test that runs a copy of the logic tests nothing about the
contract. Here, a change to a contract is a change to what these tests run.

lib/bracket_consensus.py is a curated reading copy of the same rules. The last
class in this file asserts it has not drifted from the contracts, because a
reference copy that quietly disagrees with the thing it documents is worse than
no reference copy.
"""

import itertools
import pathlib
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"

BEGIN = "# --- PURE RULES BEGIN"
END = "# --- PURE RULES END"


def pure_section(name):
    """Execute the marked pure section of a contract and return its namespace."""
    src = (CONTRACTS / name).read_text(encoding="utf-8")
    assert BEGIN in src, "%s has no PURE RULES BEGIN marker" % name
    assert END in src, "%s has no PURE RULES END marker" % name
    # Drop the remainder of the marker line itself, or its trailing dashes
    # arrive as the first line of the body and Python reads them as an indent.
    body = src.split(BEGIN, 1)[1].split("\n", 1)[1].split(END, 1)[0]
    ns = {}
    exec(compile(body, "%s::pure" % name, "exec"), ns)
    return ns


TB = pure_section("tiebreak.py")


# ---------------------------------------------------------------------------
# normalise_side — the closed vocabulary
# ---------------------------------------------------------------------------

class TestNormaliseSide:
    @pytest.mark.parametrize("raw", ["a", "A", " a ", "Item A", "item a", "first", "LEFT"])
    def test_every_spelling_of_a_maps_to_a(self, raw):
        assert TB["normalise_side"](raw) == "a"

    @pytest.mark.parametrize("raw", ["b", "B", " b ", "Item B", "second", "right"])
    def test_every_spelling_of_b_maps_to_b(self, raw):
        assert TB["normalise_side"](raw) == "b"

    @pytest.mark.parametrize(
        "raw",
        ["", "   ", "neither", "both", "unclear", "maybe a", "c", "1", "null",
         None, 42, [], {}, "a and b"],
    )
    def test_everything_else_is_neither(self, raw):
        assert TB["normalise_side"](raw) == "neither"

    def test_an_unknown_answer_can_never_win_a_round(self):
        # The safe direction. An unreadable round may produce TIED, never a
        # winner; mapping an unknown answer onto a side would let a malformed
        # response decide a comparison.
        for raw in ["garbage", "ITEM C", "", None]:
            assert TB["normalise_side"](raw) not in ("a", "b")


# ---------------------------------------------------------------------------
# combine_rounds — nine combinations, two of them real
# ---------------------------------------------------------------------------

SIDES = ["a", "b", "neither"]


class TestCombineRounds:
    def test_a_wins_only_when_it_wins_both_orders(self):
        assert TB["combine_rounds"]("a", "a") == "a"

    def test_b_wins_only_when_it_wins_both_orders(self):
        assert TB["combine_rounds"]("b", "b") == "b"

    @pytest.mark.parametrize(
        "f,r",
        [(f, r) for f in SIDES for r in SIDES if not (f == r and f in ("a", "b"))],
    )
    def test_every_other_combination_is_tied(self, f, r):
        assert TB["combine_rounds"](f, r) == "tied"

    def test_exactly_two_of_the_nine_combinations_are_decisive(self):
        decisive = [
            (f, r)
            for f in SIDES
            for r in SIDES
            if TB["combine_rounds"](f, r) != "tied"
        ]
        assert decisive == [("a", "a"), ("b", "b")]

    def test_pure_position_bias_is_named_as_tied(self):
        # The model names whichever item it saw first. Forward shows A first so
        # it says a; reverse shows B first so it says b. This is the exact
        # failure the contract exists to catch, and it must not produce a
        # winner.
        assert TB["combine_rounds"]("a", "b") == "tied"

    def test_the_answer_moving_with_the_order_is_never_a_winner(self):
        assert TB["combine_rounds"]("b", "a") == "tied"

    def test_unrecognised_rounds_collapse_to_tied(self):
        assert TB["combine_rounds"]("something", "else") == "tied"

    def test_swapping_the_two_rounds_swaps_the_winner_or_keeps_the_tie(self):
        # Not symmetry of an agreement rule, but a sanity property: the roles of
        # the rounds are interchangeable, so swapping them cannot invent a
        # winner that did not survive both orders.
        for f, r in itertools.product(SIDES, repeat=2):
            direct = TB["combine_rounds"](f, r)
            swapped = TB["combine_rounds"](r, f)
            assert direct == swapped


# ---------------------------------------------------------------------------
# tiebreak_agrees — the two layers
# ---------------------------------------------------------------------------

def proposal(forward, reverse, verdict=None):
    """A well-formed proposal, unless `verdict` is overridden to lie."""
    v = TB["combine_rounds"](forward, reverse) if verdict is None else verdict
    return {"forward": forward, "reverse": reverse, "verdict": v,
            "why_forward": "", "why_reverse": ""}


class TestTiebreakAgrees:
    def test_two_identical_honest_proposals_agree(self):
        p = proposal("a", "a")
        assert TB["tiebreak_agrees"](p, p) is True

    def test_two_honest_nodes_differing_on_one_round_still_agree_on_tied(self):
        # The whole reason layer 2 compares the verdict and not the rounds.
        mine = proposal("a", "b")      # tied
        theirs = proposal("neither", "a")  # also tied
        assert TB["tiebreak_agrees"](mine, theirs) is True

    def test_different_verdicts_do_not_agree(self):
        assert TB["tiebreak_agrees"](proposal("a", "a"), proposal("b", "b")) is False

    def test_a_leader_lying_about_its_own_rounds_is_caught_for_free(self):
        # LAYER 1. The rounds say tied; the proposal claims a. No prompt has to
        # run to know this is false.
        liar = proposal("a", "b", verdict="a")
        honest = proposal("a", "b")
        assert TB["tiebreak_agrees"](honest, liar) is False

    def test_a_liar_is_rejected_even_when_the_verdicts_match(self):
        # Both claim "a", but the liar's own rounds do not produce it.
        liar = proposal("a", "neither", verdict="a")
        honest = proposal("a", "a")
        assert TB["tiebreak_agrees"](honest, liar) is False

    @pytest.mark.parametrize("bad", ["", "A", "tie", "winner", "neither", "0", None])
    def test_a_verdict_outside_the_vocabulary_is_refused(self, bad):
        p = dict(proposal("a", "a"))
        p["verdict"] = bad
        assert TB["tiebreak_agrees"](proposal("a", "a"), p) is False

    def test_a_missing_field_is_refused_rather_than_defaulted(self):
        assert TB["tiebreak_agrees"]({}, proposal("a", "a")) is False
        assert TB["tiebreak_agrees"](proposal("a", "a"), {}) is False

    @pytest.mark.parametrize(
        "mine,theirs",
        list(itertools.product(
            [("a", "a"), ("b", "b"), ("a", "b"), ("neither", "neither"),
             ("b", "a"), ("a", "neither")],
            repeat=2,
        )),
    )
    def test_the_rule_is_symmetric(self, mine, theirs):
        m, t = proposal(*mine), proposal(*theirs)
        assert TB["tiebreak_agrees"](m, t) == TB["tiebreak_agrees"](t, m)

    def test_the_rule_is_symmetric_with_a_liar_on_either_side(self):
        liar = proposal("a", "b", verdict="b")
        honest = proposal("b", "b")
        assert TB["tiebreak_agrees"](liar, honest) == TB["tiebreak_agrees"](honest, liar)


# ---------------------------------------------------------------------------
# sanitise_reason
# ---------------------------------------------------------------------------

class TestSanitiseReason:
    def test_markup_is_stripped(self):
        out = TB["sanitise_reason"]("<script>alert(1)</script> it is longer")
        assert "<" not in out and ">" not in out
        assert "it is longer" in out

    def test_braces_backticks_and_brackets_go(self):
        out = TB["sanitise_reason"]("a {b} `c` [d] \\e")
        for ch in "{}`[]\\":
            assert ch not in out

    def test_control_characters_become_spaces(self):
        out = TB["sanitise_reason"]("one\x00two\x1ftwo")
        assert "\x00" not in out and "\x1f" not in out
        # Words either side of a control character must not fuse.
        assert "onetwo" not in out

    def test_whitespace_is_collapsed(self):
        assert TB["sanitise_reason"]("  a   b \n c ") == "a b c"

    def test_it_is_capped(self):
        assert len(TB["sanitise_reason"]("x" * 5000)) == 300

    def test_a_non_string_does_not_raise(self):
        assert TB["sanitise_reason"](None) == "None"
        assert TB["sanitise_reason"](12) == "12"


# ---------------------------------------------------------------------------
# prompt symmetry — load-bearing
# ---------------------------------------------------------------------------

class TestPromptSymmetry:
    CRIT = "which explains the tradeoff more clearly"
    ITEM_A = "the first item, at some length"
    ITEM_B = "the second item, also at some length"

    def forward(self):
        return TB["build_prompt"](self.CRIT, "a", self.ITEM_A, "b", self.ITEM_B)

    def reverse(self):
        return TB["build_prompt"](self.CRIT, "b", self.ITEM_B, "a", self.ITEM_A)

    def test_the_two_prompts_have_identical_line_structure(self):
        # If the two prompts differed in shape, a disagreement between them
        # would measure the PROMPTS rather than the model, and the primitive
        # would mean nothing.
        assert len(self.forward().split("\n")) == len(self.reverse().split("\n"))

    def test_both_prompts_share_every_scaffolding_phrase(self):
        f, r = self.forward(), self.reverse()
        for phrase in [
            "You are comparing two items against one criterion.",
            "Criterion: " + self.CRIT,
            "Which item better meets the criterion?",
            "Answer \"neither\" if the criterion does not separate them.",
            "Reply with JSON:",
        ]:
            assert phrase in f, phrase
            assert phrase in r, phrase

    def test_the_two_prompts_differ_only_in_the_order_of_the_items(self):
        f, r = self.forward(), self.reverse()
        assert f != r
        # Same characters, rearranged: nothing is added or removed by swapping.
        assert sorted(f) == sorted(r)

    def test_both_items_appear_in_both_prompts(self):
        for p in (self.forward(), self.reverse()):
            assert self.ITEM_A in p and self.ITEM_B in p

    def test_the_labels_stay_bound_to_the_items_not_the_positions(self):
        # In the reverse prompt item B is shown first, but it is still labelled
        # "Item b". A relabelling would make a changed answer meaningless.
        r = self.reverse()
        assert r.index("Item b:") < r.index("Item a:")
        assert r.index(self.ITEM_B) < r.index(self.ITEM_A)


# ---------------------------------------------------------------------------
# percentages, without a float crossing the boundary
# ---------------------------------------------------------------------------

class TestPercentages:
    @pytest.mark.parametrize(
        "part,whole,text",
        [(0, 0, "0.0"), (0, 10, "0.0"), (10, 10, "100.0"), (1, 3, "33.3"),
         (2, 3, "66.7"), (1, 8, "12.5"), (1, 2, "50.0")],
    )
    def test_the_decimal_string_is_canonical(self, part, whole, text):
        assert TB["pct_text"](part, whole) == text

    def test_the_scaled_integer_matches_the_string(self):
        for whole in range(1, 40):
            for part in range(0, whole + 1):
                text = TB["pct_text"](part, whole)
                scaled = TB["pct_scaled"](part, whole)
                assert str(scaled // 10) + "." + str(scaled % 10) == text

    def test_a_zero_total_does_not_divide_by_zero(self):
        assert TB["pct_text"](0, 0) == "0.0"
        assert TB["pct_scaled"](0, 0) == 0

    def test_no_float_is_returned(self):
        assert isinstance(TB["pct_text"](1, 3), str)
        assert isinstance(TB["pct_scaled"](1, 3), int)


# ---------------------------------------------------------------------------
# the curated reading copy must not drift
# ---------------------------------------------------------------------------

class TestLibraryMatchesTheContracts:
    """lib/bracket_consensus.py is documentation that runs. Keep it honest."""

    @staticmethod
    def lib():
        ns = {}
        src = (ROOT / "lib" / "bracket_consensus.py").read_text(encoding="utf-8")
        exec(compile(src, "bracket_consensus", "exec"), ns)
        return ns

    def test_normalise_side_agrees(self):
        lib = self.lib()
        for raw in ["a", "b", "A", "Item B", "first", "second", "", "junk", None]:
            assert lib["normalise_side"](raw) == TB["normalise_side"](raw)

    def test_combine_rounds_agrees(self):
        lib = self.lib()
        for f, r in itertools.product(["a", "b", "neither", "junk"], repeat=2):
            assert lib["combine_rounds"](f, r) == TB["combine_rounds"](f, r)

    def test_tiebreak_agrees_agrees(self):
        lib = self.lib()
        cases = [("a", "a"), ("b", "b"), ("a", "b"), ("neither", "a")]
        for m, t in itertools.product(cases, repeat=2):
            pm, pt = proposal(*m), proposal(*t)
            assert lib["tiebreak_agrees"](pm, pt) == TB["tiebreak_agrees"](pm, pt)

    def test_sanitise_reason_agrees(self):
        lib = self.lib()
        for raw in ["<b>x</b>", "a\x00b", "  spaced   out ", "`tick`", "x" * 400]:
            assert lib["sanitise_reason"](raw) == TB["sanitise_reason"](raw)


SL = pure_section("slate.py")
CU = pure_section("cutline.py")
WI = pure_section("winnow.py")


# ---------------------------------------------------------------------------
# scores and orders
# ---------------------------------------------------------------------------

class TestParseScores:
    def test_a_well_formed_row_parses(self):
        assert SL["parse_scores"]("88.0|71.5|70.9", 3) == [88.0, 71.5, 70.9]

    @pytest.mark.parametrize("text,n", [("1|2", 3), ("1|2|3", 2), ("", 3), ("1||3", 3)])
    def test_a_count_mismatch_or_gap_is_refused(self, text, n):
        assert SL["parse_scores"](text, n) is None

    @pytest.mark.parametrize("bad", ["inf", "-inf", "nan", "1e400", "-1e400"])
    def test_non_finite_is_a_failure_never_a_value(self, bad):
        # Infinity is within `closeness` of nothing, so an infinity reaching
        # banding would make the bands depend on arithmetic nobody intended.
        assert SL["parse_scores"]("1.0|" + bad, 2) is None

    def test_junk_is_refused(self):
        assert SL["parse_scores"]("a|b", 2) is None

    def test_zero_items_is_refused(self):
        assert SL["parse_scores"]("", 0) is None

    def test_negative_and_zero_scores_are_fine(self):
        assert SL["parse_scores"]("-5|0|5", 3) == [-5.0, 0.0, 5.0]


class TestPermutations:
    @pytest.mark.parametrize("order", [[0], [0, 1], [2, 0, 1], [3, 2, 1, 0]])
    def test_a_real_permutation_is_accepted(self, order):
        assert SL["is_permutation"](order, len(order)) is True

    @pytest.mark.parametrize(
        "order,n",
        [([0, 0], 2), ([0, 2], 2), ([-1, 0], 2), ([0, 1, 2], 2), ([0], 2), ([1], 2)],
    )
    def test_anything_else_is_refused(self, order, n):
        # A model that repeats an index has dropped an item, and a ranking that
        # silently omits an item is worse than none: it looks complete.
        assert SL["is_permutation"](order, n) is False

    def test_parse_order_refuses_a_repeat(self):
        assert SL["parse_order"]("0|0|2", 3) is None

    def test_parse_order_refuses_non_digits(self):
        assert SL["parse_order"]("0|x|2", 3) is None
        assert SL["parse_order"]("0|-1|2", 3) is None

    def test_parse_order_accepts_a_permutation(self):
        assert SL["parse_order"]("2|0|1", 3) == [2, 0, 1]


# ---------------------------------------------------------------------------
# banding — the heart of the family
# ---------------------------------------------------------------------------

class TestBandScores:
    def test_a_clean_separation_gives_one_band_each(self):
        assert SL["band_scores"]([90.0, 50.0, 10.0], 5.0) == [1, 2, 3]

    def test_adjacent_scores_within_the_threshold_share_a_band(self):
        assert SL["band_scores"]([88.0, 71.5, 70.9, 40.0], 2.0) == [1, 2, 2, 3]

    def test_banding_is_transitive_along_the_run(self):
        # a close to b, b close to c, so all three share a band even though a
        # and c are further apart than the threshold. The alternative depends on
        # which pair you compare first, which is not deterministic in any useful
        # sense and so cannot be what consensus rests on.
        assert SL["band_scores"]([10.0, 9.0, 8.0], 1.5) == [1, 1, 1]
        assert abs(10.0 - 8.0) > 1.5

    def test_a_zero_threshold_still_bands_exact_equals(self):
        assert SL["band_scores"]([5.0, 5.0, 4.0], 0.0) == [1, 1, 2]

    def test_a_huge_threshold_collapses_everything(self):
        assert SL["band_scores"]([100.0, 0.0], 1000.0) == [1, 1]

    def test_the_boundary_is_inclusive(self):
        # Exactly `closeness` apart still shares a band: the rule is "differ by
        # MORE than the threshold to be separated".
        assert SL["band_scores"]([10.0, 8.0], 2.0) == [1, 1]
        assert SL["band_scores"]([10.0, 7.9], 2.0) == [1, 2]

    def test_an_empty_run_bands_to_nothing(self):
        assert SL["band_scores"]([], 1.0) == []

    def test_every_contract_that_bands_bands_identically(self):
        for scores, close in [([88.0, 71.5, 70.9, 40.0], 2.0),
                              ([10.0, 9.0, 8.0], 1.5),
                              ([5.0, 5.0, 4.0], 0.0)]:
            assert SL["band_scores"](scores, close) == CU["band_scores"](scores, close)


class TestUndifferentiated:
    def test_everything_in_one_band_is_a_finding(self):
        assert SL["is_undifferentiated"]([1, 1, 1]) is True

    def test_any_separation_is_not(self):
        assert SL["is_undifferentiated"]([1, 1, 2]) is False

    def test_an_empty_run_is_not_undifferentiated(self):
        assert SL["is_undifferentiated"]([]) is False


class TestCanonicalOrder:
    def test_the_string_carries_index_and_band(self):
        assert SL["canonical_order"]([2, 0, 1, 3], [1, 2, 2, 3]) == "2:1|0:2|1:2|3:3"

    def test_the_order_inside_a_band_carries_no_weight(self):
        # The contract has already said it will not separate these two, so the
        # order between them must not decide whether consensus settles.
        a = SL["canonical_order"]([0, 1], [1, 1])
        b = SL["canonical_order"]([1, 0], [1, 1])
        assert a == b == "0:1|1:1"

    def test_the_order_between_bands_is_preserved(self):
        # Across a band boundary the order is the whole answer.
        a = SL["canonical_order"]([0, 1], [1, 2])
        b = SL["canonical_order"]([1, 0], [1, 2])
        assert a == "0:1|1:2"
        assert b == "1:1|0:2"
        assert a != b


class TestSlateAgrees:
    N = 4
    CLOSE = 2.0

    def payload(self, order, scores):
        return {"order": order, "scores": scores}

    def test_identical_results_agree(self):
        p = self.payload("2|0|1|3", "88.0|71.5|70.9|40.0")
        assert SL["slate_agrees"](p, p, self.N, self.CLOSE) is True

    def test_two_nodes_swapping_a_tied_adjacent_pair_still_agree(self):
        # The exact failure that makes strict_eq on a raw ordering useless.
        a = self.payload("2|0|1|3", "88.0|71.5|70.9|40.0")
        b = self.payload("2|1|0|3", "88.0|70.9|71.5|40.0")
        assert SL["slate_agrees"](a, b, self.N, self.CLOSE) is True

    def test_reversing_the_top_two_does_not_agree(self):
        # The only part anyone cares about.
        a = self.payload("0|1|2|3", "90.0|60.0|40.0|10.0")
        b = self.payload("1|0|2|3", "60.0|90.0|40.0|10.0")
        assert SL["slate_agrees"](a, b, self.N, self.CLOSE) is False

    def test_an_unusable_payload_never_agrees(self):
        good = self.payload("2|0|1|3", "88.0|71.5|70.9|40.0")
        for bad in [self.payload("0|0|1|3", "1|2|3|4"),
                    self.payload("2|0|1|3", "1|2|3"),
                    self.payload("", ""),
                    self.payload("2|0|1|3", "1|2|nan|4")]:
            assert SL["slate_agrees"](good, bad, self.N, self.CLOSE) is False
            assert SL["slate_agrees"](bad, good, self.N, self.CLOSE) is False

    def test_two_unusable_payloads_do_not_agree_with_each_other(self):
        bad = self.payload("nonsense", "nonsense")
        assert SL["slate_agrees"](bad, bad, self.N, self.CLOSE) is False

    @pytest.mark.parametrize(
        "a,b",
        list(itertools.product(
            [("2|0|1|3", "88.0|71.5|70.9|40.0"),
             ("2|1|0|3", "88.0|70.9|71.5|40.0"),
             ("0|1|2|3", "90.0|60.0|40.0|10.0"),
             ("0|0|1|3", "1|2|3|4")],
            repeat=2,
        )),
    )
    def test_the_rule_is_symmetric(self, a, b):
        pa, pb = self.payload(*a), self.payload(*b)
        assert (SL["slate_agrees"](pa, pb, self.N, self.CLOSE)
                == SL["slate_agrees"](pb, pa, self.N, self.CLOSE))


# ---------------------------------------------------------------------------
# the cut
# ---------------------------------------------------------------------------

class TestCutAt:
    def test_a_clean_boundary_selects_exactly_k(self):
        assert CU["cut_at"]([1, 2, 3, 4], 2, "refuse") == (2, False)
        assert CU["cut_at"]([1, 2, 3, 4], 2, "expand") == (2, False)

    def test_k_at_or_past_the_end_selects_everything(self):
        assert CU["cut_at"]([1, 2], 2, "refuse") == (2, False)
        assert CU["cut_at"]([1, 2], 5, "refuse") == (2, False)

    def test_refuse_selects_nobody_when_the_cut_falls_inside_a_band(self):
        # Correct when K is a hard budget. An arbitrary cut that still returned
        # a selection would be noise dressed as a decision.
        assert CU["cut_at"]([1, 2, 2, 3], 2, "refuse") == (0, True)

    def test_expand_takes_the_whole_tied_band(self):
        # Correct when K is a target and fairness matters more than the count.
        assert CU["cut_at"]([1, 2, 2, 3], 2, "expand") == (3, False)

    def test_expand_runs_to_the_end_of_a_trailing_tie(self):
        assert CU["cut_at"]([1, 2, 2, 2], 2, "expand") == (4, False)

    def test_a_zero_or_negative_k_selects_nobody(self):
        assert CU["cut_at"]([1, 2, 3], 0, "refuse") == (0, False)
        assert CU["cut_at"]([1, 2, 3], -1, "refuse") == (0, False)

    def test_the_policy_changes_the_answer_which_is_why_it_is_a_parameter(self):
        bands = [1, 1, 1, 2]
        assert CU["cut_at"](bands, 2, "refuse") != CU["cut_at"](bands, 2, "expand")


class TestCanonicalSelection:
    def test_membership_is_sorted_so_order_cannot_matter(self):
        assert CU["canonical_selection"]([7, 0, 3]) == "0|3|7"
        assert CU["canonical_selection"]([3, 7, 0]) == "0|3|7"

    def test_an_empty_selection_is_an_empty_string(self):
        assert CU["canonical_selection"]([]) == ""


class TestCutlineAgrees:
    N = 4
    CLOSE = 2.0
    K = 2

    def payload(self, order, scores):
        return {"order": order, "scores": scores}

    def test_two_nodes_ordering_the_selected_pair_differently_still_agree(self):
        # The rung below Slate: who is in, not who is first.
        a = self.payload("0|1|2|3", "90.0|80.0|40.0|10.0")
        b = self.payload("1|0|2|3", "80.0|90.0|40.0|10.0")
        assert CU["cutline_agrees"](a, b, self.N, self.CLOSE, self.K, "refuse") is True

    def test_a_different_membership_does_not_agree(self):
        a = self.payload("0|1|2|3", "90.0|80.0|40.0|10.0")
        b = self.payload("0|2|1|3", "90.0|80.0|40.0|10.0")
        assert CU["cutline_agrees"](a, b, self.N, self.CLOSE, self.K, "refuse") is False

    def test_nodes_disagreeing_about_whether_the_cut_was_arbitrary_do_not_agree(self):
        # One node sees the cut fall inside a tied band and refuses; the other
        # sees a clean boundary and selects two. Both are internally coherent
        # and they have not agreed about anything worth recording.
        a = self.payload("0|1|2|3", "90.0|89.0|88.0|10.0")   # bands 1,1,1,2
        b = self.payload("0|1|2|3", "90.0|80.0|40.0|10.0")   # bands 1,2,3,4
        assert CU["cutline_agrees"](a, b, self.N, self.CLOSE, self.K, "refuse") is False

    @pytest.mark.parametrize("policy", ["refuse", "expand"])
    @pytest.mark.parametrize(
        "a,b",
        list(itertools.product(
            [("0|1|2|3", "90.0|80.0|40.0|10.0"),
             ("1|0|2|3", "80.0|90.0|40.0|10.0"),
             ("0|1|2|3", "90.0|89.0|40.0|10.0"),
             ("0|0|2|3", "1|2|3|4")],
            repeat=2,
        )),
    )
    def test_the_rule_is_symmetric(self, a, b, policy):
        pa, pb = self.payload(*a), self.payload(*b)
        assert (CU["cutline_agrees"](pa, pb, self.N, self.CLOSE, self.K, policy)
                == CU["cutline_agrees"](pb, pa, self.N, self.CLOSE, self.K, policy))


# ---------------------------------------------------------------------------
# the partition
# ---------------------------------------------------------------------------

class TestNormaliseBucket:
    @pytest.mark.parametrize("raw", ["accept", "ACCEPT", " accepted ", "pass", "yes"])
    def test_accept_spellings(self, raw):
        assert WI["normalise_bucket"](raw) == "accept"

    @pytest.mark.parametrize("raw", ["reject", "REJECTED", "fail", "no"])
    def test_reject_spellings(self, raw):
        assert WI["normalise_bucket"](raw) == "reject"

    @pytest.mark.parametrize("raw", ["review", "", "maybe", "unsure", None, 7, "acc"])
    def test_everything_unrecognised_lands_in_review(self, raw):
        # The safe direction: an unreadable label sends the item to a human
        # rather than silently acting on it.
        assert WI["normalise_bucket"](raw) == "review"


class TestPartitionAgrees:
    def test_identical_partitions_agree(self):
        p = ["accept", "reject", "review"]
        assert WI["partition_agrees"](p, p, 3) is True

    def test_one_item_drifting_through_review_is_forgiven(self):
        # An item genuinely near a boundary can honestly land either side. Two
        # validators disagreeing about one such item is the standard working.
        a = ["accept", "reject", "review"]
        b = ["accept", "reject", "accept"]
        assert WI["partition_agrees"](a, b, 3) is True

    def test_two_items_drifting_is_not_forgiven(self):
        a = ["review", "review", "accept"]
        b = ["accept", "reject", "accept"]
        assert WI["partition_agrees"](a, b, 3) is False

    def test_accept_to_reject_is_never_forgiven(self):
        # Nothing near a boundary crosses two buckets at once. Forgiving this
        # would let two nodes disagree about whether an item passes and still
        # settle, and the record would look decisive.
        a = ["accept", "review", "review"]
        b = ["reject", "review", "review"]
        assert WI["partition_agrees"](a, b, 3) is False

    def test_a_length_mismatch_is_refused(self):
        assert WI["partition_agrees"](["accept"], ["accept", "reject"], 2) is False
        assert WI["partition_agrees"](["accept", "reject"], ["accept"], 2) is False

    @pytest.mark.parametrize(
        "a,b",
        list(itertools.product(
            [["accept", "reject", "review"],
             ["accept", "reject", "accept"],
             ["reject", "reject", "review"],
             ["review", "review", "review"],
             ["accept", "accept", "accept"]],
            repeat=2,
        )),
    )
    def test_the_rule_is_symmetric(self, a, b):
        assert WI["partition_agrees"](a, b, 3) == WI["partition_agrees"](b, a, 3)


class TestTooVague:
    def test_a_batch_mostly_in_review_is_refused(self):
        # A standard that sends most of a batch to a human has not triaged it.
        p = ["review", "review", "review", "accept"]
        assert WI["is_too_vague"](p, 50) is True

    def test_a_batch_inside_the_declared_fraction_is_fine(self):
        p = ["review", "accept", "accept", "reject"]
        assert WI["is_too_vague"](p, 50) is False

    def test_exactly_at_the_threshold_is_allowed(self):
        # "more than" the declared fraction, not "at least".
        p = ["review", "review", "accept", "reject"]
        assert WI["is_too_vague"](p, 50) is False

    def test_zero_tolerance_refuses_any_review(self):
        assert WI["is_too_vague"](["review", "accept"], 0) is True
        assert WI["is_too_vague"](["accept", "accept"], 0) is False

    def test_full_tolerance_never_refuses(self):
        assert WI["is_too_vague"](["review", "review"], 100) is False

    def test_an_empty_batch_is_not_vague(self):
        assert WI["is_too_vague"]([], 50) is False

    def test_the_threshold_is_integer_arithmetic_throughout(self):
        # A percentage computed in floats would compare differently on two nodes
        # at the exact boundary.
        for n in range(1, 12):
            for r in range(0, n + 1):
                p = ["review"] * r + ["accept"] * (n - r)
                assert WI["is_too_vague"](p, 50) == (r * 100 > 50 * n)


# ---------------------------------------------------------------------------
# the same helper, inlined four times, must behave the same way
# ---------------------------------------------------------------------------

class TestSharedHelpersAgree:
    def test_sanitise_reason_is_identical_everywhere(self):
        for raw in ["<b>x</b>", "a\x00b", "  spaced   out ", "`tick`", "x" * 400]:
            got = {ns["sanitise_reason"](raw) for ns in (TB, SL, CU, WI)}
            assert len(got) == 1, got

    def test_split_items_drops_empties_and_collapses_whitespace(self):
        for ns in (SL, CU, WI):
            assert ns["split_items"]("a |  b  |  | c ") == ["a", "b", "c"]

    def test_is_permutation_is_identical_in_slate_and_cutline(self):
        for order, n in [([0, 1], 2), ([1, 0], 2), ([0, 0], 2), ([2], 2)]:
            assert SL["is_permutation"](order, n) == CU["is_permutation"](order, n)

    def test_parse_scores_is_identical_in_slate_and_cutline(self):
        for text, n in [("1|2", 2), ("1|nan", 2), ("1|2|3", 2), ("inf|1", 2)]:
            assert SL["parse_scores"](text, n) == CU["parse_scores"](text, n)


class TestClosedVocabularies:
    """Each contract declares its vocabulary as a constant. Bind it to the
    function, or the constant is documentation that nothing enforces."""

    def test_every_bucket_normalise_returns_is_in_BUCKETS(self):
        for raw in ["accept", "reject", "review", "pass", "fail", "yes", "no",
                    "", "banana", None, 7, "ACCEPTED", "  Review  "]:
            assert WI["normalise_bucket"](raw) in WI["BUCKETS"]

    def test_BUCKETS_holds_exactly_the_three_labels(self):
        assert set(WI["BUCKETS"]) == {"accept", "reject", "review"}
        assert len(WI["BUCKETS"]) == 3

    def test_every_side_normalise_returns_is_a_known_side(self):
        for raw in ["a", "b", "first", "second", "", "junk", None, 7]:
            assert TB["normalise_side"](raw) in (TB["A"], TB["B"], TB["NEITHER"])

    def test_every_verdict_combine_produces_is_in_VERDICTS(self):
        for f in SIDES + ["junk", ""]:
            for r in SIDES + ["junk", ""]:
                assert TB["combine_rounds"](f, r) in TB["VERDICTS"]

    def test_ON_TIE_holds_exactly_the_two_policies(self):
        assert set(CU["ON_TIE"]) == {"refuse", "expand"}

    def test_parse_closeness_is_identical_in_slate_and_cutline(self):
        # Both contracts band against this threshold; a disagreement here would
        # make the same slate settle in one and not the other.
        for text in ["2.0", "0", "1000", "-1", "nan", "inf", "", "abc", "1e400"]:
            assert SL["parse_closeness"](text) == CU["parse_closeness"](text)

    def test_parse_order_is_identical_in_slate_and_cutline(self):
        for text, n in [("0|1", 2), ("1|0", 2), ("0|0", 2), ("x|1", 2), ("0|1|2", 2)]:
            assert SL["parse_order"](text, n) == CU["parse_order"](text, n)
