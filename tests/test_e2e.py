"""The contracts, executed, plus the static shape tests.

Two kinds of test live here.

STATIC SHAPE TESTS read the contract source and assert things about its shape.
They are not tests of behaviour, and that is exactly why they exist: every one
of them corresponds to a GenVM failure that behaviour tests cannot see, because
the contract behaves perfectly on a workstation and then fails at deploy or
returns Result Code <unknown> with no traceback. They run against all four
contracts.

END TO END TESTS run the real contract on tests/glsim.py. The critical property
is that the leader and the validator get their OWN mock answers:

    self.mocks(CLEAN, v_prompts=SWAPPED)   # the validator saw a different round

Every mocking framework feeds both nodes the same data by default, which is
precisely why a contract that quietly assumes both nodes see identical bytes
passes its suite and then fails on a real network.
"""

import ast
import pathlib
import pytest

import glsim
from glsim import gl

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"

CONTRACT_FILES = sorted(p.name for p in CONTRACTS.glob("*.py"))

RUNNER_HEADER = (
    '# { "Depends": '
    '"py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }'
)


def source(name):
    return (CONTRACTS / name).read_text(encoding="utf-8")


def tree(name):
    return ast.parse(source(name))


def classes(name):
    return [n for n in ast.walk(tree(name)) if isinstance(n, ast.ClassDef)]


def contract_class(name):
    for c in classes(name):
        for b in c.bases:
            if isinstance(b, ast.Attribute) and b.attr == "Contract":
                return c
    raise AssertionError("%s has no Contract class" % name)


def annotation_text(node):
    return ast.unparse(node) if node is not None else ""


# ===========================================================================
# static shape tests — one per GenVM failure that behaviour cannot see
# ===========================================================================

@pytest.mark.parametrize("name", CONTRACT_FILES)
class TestShape:

    def test_the_runner_header_is_pinned(self, name):
        # A floating tag like py-genlayer:test is rejected at deploy. This exact
        # hash is confirmed working on studionet.
        first = source(name).split("\n", 1)[0].strip()
        assert first == RUNNER_HEADER, first

    def test_no_storage_dataclass_holds_a_collection(self, name):
        # The deploy failure. A storage dataclass containing a DynArray or
        # TreeMap cannot be built: the first write dies with "this class can't
        # be instantiated by user", and inmem_allocate does not rescue it.
        for c in classes(name):
            decorators = {ast.unparse(d) for d in c.decorator_list}
            if "allow_storage" not in decorators:
                continue
            for stmt in c.body:
                if isinstance(stmt, ast.AnnAssign):
                    ann = annotation_text(stmt.annotation)
                    assert not ann.startswith("DynArray"), (name, c.name, ann)
                    assert not ann.startswith("TreeMap"), (name, c.name, ann)

    def test_no_forbidden_storage_types(self, name):
        # int, list, dict and tuple are rejected at deploy.
        forbidden = {"int", "list", "dict", "tuple", "set", "float"}
        for c in classes(name):
            decorators = {ast.unparse(d) for d in c.decorator_list}
            is_storage = "allow_storage" in decorators or c is contract_class(name)
            if not is_storage:
                continue
            for stmt in c.body:
                if isinstance(stmt, ast.AnnAssign):
                    ann = annotation_text(stmt.annotation)
                    head = ann.split("[", 1)[0]
                    assert head not in forbidden, (name, c.name, ann)

    def test_only_fully_instantiated_generics(self, name):
        # Bare TreeMap or DynArray is refused at deploy.
        for c in classes(name):
            for stmt in c.body:
                if isinstance(stmt, ast.AnnAssign):
                    ann = annotation_text(stmt.annotation)
                    assert ann not in ("DynArray", "TreeMap"), (name, c.name)

    def test_no_storage_field_is_declared_twice(self, name):
        # Python keeps the last one and says nothing. A duplicated annotation
        # once shipped to a live repository and changed the on-chain layout.
        for c in classes(name):
            seen = []
            for stmt in c.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    seen.append(stmt.target.id)
            dupes = {f for f in seen if seen.count(f) > 1}
            assert not dupes, (name, c.name, sorted(dupes))

    def test_no_method_is_defined_twice(self, name):
        # A silently shadowed method. A duplicated lookup helper once made a
        # mutation test pass that should have failed.
        for c in classes(name):
            names = [s.name for s in c.body if isinstance(s, ast.FunctionDef)]
            dupes = {m for m in names if names.count(m) > 1}
            assert not dupes, (name, c.name, sorted(dupes))

    def test_every_persistent_field_is_declared_in_the_class_body(self, name):
        # self.x = value on an undeclared name is silently discarded after
        # execution. Nothing warns; the contract appears to work and loses data.
        cls = contract_class(name)
        declared = {
            s.target.id
            for s in cls.body
            if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)
        }
        for node in ast.walk(cls):
            if not isinstance(node, ast.Assign):
                continue
            for t in node.targets:
                if (
                    isinstance(t, ast.Attribute)
                    and isinstance(t.value, ast.Name)
                    and t.value.id == "self"
                ):
                    assert t.attr in declared, (name, t.attr)

    def test_no_public_method_takes_a_builtin_container(self, name):
        # A list parameter is close enough to a documented GenVM restriction to
        # be a bet rather than a decision. Collections are pipe-joined strings.
        allowed = {"str", "u256", "u8", "i256", "bool", "Address", "bytes"}
        cls = contract_class(name)
        for fn in cls.body:
            if not isinstance(fn, ast.FunctionDef):
                continue
            decorators = {ast.unparse(d) for d in fn.decorator_list}
            if not any(d.startswith("gl.public") for d in decorators):
                continue
            for arg in fn.args.args:
                if arg.arg == "self":
                    continue
                ann = annotation_text(arg.annotation)
                assert ann in allowed, (name, fn.name, arg.arg, ann)

    def test_every_raise_inside_the_contract_is_a_user_error(self, name):
        # Any other exception surfaces as a contract error with a raw traceback.
        cls = contract_class(name)
        for node in ast.walk(cls):
            if isinstance(node, ast.Raise) and node.exc is not None:
                assert ast.unparse(node.exc).startswith("gl.vm.UserError"), (
                    name, ast.unparse(node.exc),
                )

    def test_every_view_bounds_checks_through_a_guarded_lookup(self, name):
        # An id past the end raises a raw IndexError. Worse, Python accepts -1
        # and silently returns the newest record, correctly formatted, with
        # nothing failing anywhere.
        src = source(name)
        assert "if i < 0 or i >=" in src, name

    def test_no_block_closes_over_a_storage_object(self, name):
        # Blocks cannot read storage at all. Every value a block needs must be
        # extracted to a plain str before the block is defined.
        cls = contract_class(name)
        for fn in ast.walk(cls):
            if not isinstance(fn, ast.FunctionDef) or fn.name != "leader_fn":
                continue
            for node in ast.walk(fn):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"
                ):
                    raise AssertionError(
                        "%s: leader_fn reads self.%s" % (name, node.attr)
                    )

    def test_no_storage_object_is_compared_by_identity(self, name):
        # A storage object is a VIEW on a slot, not a copy. DynArray.__getitem__
        # builds a fresh view on every access, so `self.rows[i] is obj` is
        # always False on a node -- and it fails SILENTLY: the lookup returns
        # "not found", the view returns an empty list, and nothing raises.
        #
        # glsim cannot catch this, because its DynArray is a real Python list
        # where identity holds. Only reading the source can, which is exactly
        # what the static shape tests are for. Carry an index, never an object.
        cls = contract_class(name)
        for node in ast.walk(cls):
            if not isinstance(node, ast.Compare):
                continue
            if not any(isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops):
                continue
            for side in [node.left] + list(node.comparators):
                if isinstance(side, ast.Subscript):
                    src = ast.unparse(side)
                    assert not src.startswith("self."), (
                        "%s: identity comparison against %s" % (name, src)
                    )

    def test_no_lookup_helper_returns_a_storage_object_it_found_by_scanning(self, name):
        # The other half of the same rule. A helper that scans a collection and
        # hands back the record cannot be matched against the collection later.
        # Every _last_* helper here is annotated -> int and returns an index.
        cls = contract_class(name)
        for fn in cls.body:
            if not isinstance(fn, ast.FunctionDef) or not fn.name.startswith("_last_"):
                continue
            assert fn.returns is not None and ast.unparse(fn.returns) == "int", (
                "%s: %s must return an index, not a record" % (name, fn.name)
            )

    def test_the_block_boundary_carries_flat_strings_only(self, name):
        # THE ONE WITH NO TRACEBACK. A nested mapping or a bool in the return
        # value fails inside the calldata encoder, outside the contract, and the
        # transaction comes back with Result Code <unknown> and no stderr.
        cls = contract_class(name)
        for fn in ast.walk(cls):
            if not isinstance(fn, ast.FunctionDef) or fn.name != "leader_fn":
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Return) or node.value is None:
                    continue
                assert isinstance(node.value, ast.Dict), (
                    "%s: leader_fn must return a dict literal" % name
                )
                for v in node.value.values:
                    assert not isinstance(v, (ast.Dict, ast.List, ast.Tuple, ast.Set)), (
                        "%s: leader_fn returns a container" % name
                    )
                    if isinstance(v, ast.Constant):
                        assert isinstance(v.value, str), (
                            "%s: leader_fn returns %r" % (name, v.value)
                        )


# ===========================================================================
# Tiebreak, executed
# ===========================================================================

CRITERION = "which explains the tradeoff more clearly"
ITEM_A = "A short note that states the tradeoff and gives one worked example."
ITEM_B = "A longer note that lists benefits and never mentions a cost."

# Both items appear in BOTH prompts, labelled the same way -- only the order
# changes. So a key naming one item matches both rounds. These keys pin the
# order instead: item a followed by item b is the forward round, and the other
# way round is the reverse.
FORWARD_KEY = "Item a:\n" + ITEM_A + "\n\nItem b:"
REVERSE_KEY = "Item b:\n" + ITEM_B + "\n\nItem a:"


def rounds(forward, reverse, why_f="because", why_r="because"):
    """Mock answers keyed on the ORDER the prompt presented the items in."""
    return {
        FORWARD_KEY: {"winner": forward, "why": why_f},
        REVERSE_KEY: {"winner": reverse, "why": why_r},
    }


class TiebreakBase:
    PATH = str(CONTRACTS / "tiebreak.py")

    def deploy(self):
        glsim.set_mocks({})
        glsim.set_sender("0x" + "11" * 20)
        c = glsim.deploy(self.PATH)
        glsim.call(c, "register", CRITERION, ITEM_A, ITEM_B)
        return c

    def mocks(self, prompts, v_prompts=None):
        glsim.set_mocks(prompts, v_prompts=v_prompts)


class TestTiebreakVerdicts(TiebreakBase):
    def test_a_wins_when_it_wins_in_both_orders(self):
        c = self.deploy()
        self.mocks(rounds("a", "a"))
        glsim.call(c, "compare", 0)
        assert c.verdict(0) == "a"

    def test_b_wins_when_it_wins_in_both_orders(self):
        c = self.deploy()
        self.mocks(rounds("b", "b"))
        glsim.call(c, "compare", 0)
        assert c.verdict(0) == "b"

    def test_a_model_that_names_whichever_item_it_saw_first_is_caught(self):
        # Pure position bias: forward shows A first and it says a, reverse shows
        # B first and it says b. Consensus alone cannot see this, because every
        # validator builds the prompt the same way.
        c = self.deploy()
        self.mocks(rounds("a", "b"))
        glsim.call(c, "compare", 0)
        assert c.verdict(0) == "tied"

    def test_an_unreadable_round_produces_tied_never_a_winner(self):
        c = self.deploy()
        self.mocks(rounds("a", "gibberish"))
        glsim.call(c, "compare", 0)
        assert c.verdict(0) == "tied"

    def test_both_rounds_are_stored_for_the_record(self):
        c = self.deploy()
        self.mocks(rounds("a", "b"))
        glsim.call(c, "compare", 0)
        latest = c.latest(0)
        assert latest["rounds"]["forward"] == "a"
        assert latest["rounds"]["reverse"] == "b"
        assert latest["verdict"] == "tied"

    def test_two_prompts_run_in_one_block(self):
        c = self.deploy()
        self.mocks(rounds("a", "a"))
        glsim.call(c, "compare", 0)
        assert glsim.RT.block_runs == 1
        assert len(glsim.RT.leader_env.prompt_calls) == 2


class TestTiebreakDivergentNodes(TiebreakBase):
    def test_two_honest_nodes_differing_on_one_round_still_settle(self):
        # Leader sees a/b (tied). Validator sees neither/a (also tied). The
        # verdicts match, so the comparison stands: forcing the ROUNDS to match
        # would reject correct work.
        c = self.deploy()
        self.mocks(rounds("a", "b"), v_prompts=rounds("neither", "a"))
        glsim.call(c, "compare", 0)
        assert c.verdict(0) == "tied"
        assert glsim.RT.last_validator_verdict is True

    def test_nodes_landing_on_different_verdicts_do_not_settle(self):
        c = self.deploy()
        self.mocks(rounds("a", "a"), v_prompts=rounds("b", "b"))
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "compare", 0)
        assert glsim.RT.last_validator_verdict is False

    def test_nothing_is_written_when_consensus_fails(self):
        c = self.deploy()
        self.mocks(rounds("a", "a"), v_prompts=rounds("b", "b"))
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "compare", 0)
        assert len(c.comparisons) == 0
        assert c.verdict(0) == ""

    @pytest.mark.parametrize("junk", ["a string", ["a", "list"], 42, None])
    def test_a_model_answering_with_a_non_object_forces_rotation(self, junk):
        # The only error class reachable inside the block: these contracts make
        # no web request. Agreeing on broken model output would lock bad state,
        # so the leader classifies it and the validator disagrees.
        c = self.deploy()
        self.mocks({FORWARD_KEY: junk, REVERSE_KEY: junk})
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "compare", 0)
        assert len(c.comparisons) == 0

    def test_the_validator_really_did_run_its_own_prompts(self):
        c = self.deploy()
        self.mocks(rounds("a", "a"), v_prompts=rounds("a", "a"))
        glsim.call(c, "compare", 0)
        assert len(glsim.RT.validator_env.prompt_calls) == 2


class TestTiebreakStorage(TiebreakBase):
    def test_stability_accumulates_across_comparisons(self):
        c = self.deploy()
        for f, r in [("a", "a"), ("a", "a"), ("a", "b")]:
            self.mocks(rounds(f, r))
            glsim.call(c, "compare", 0)
        s = c.stability(0)
        assert s["comparisons"] == 3
        assert s["a"] == 2 and s["b"] == 0 and s["tied"] == 1
        assert s["tied_pct"] == "33.3"
        assert s["tied_pct_scaled"] == 333

    def test_two_pairs_do_not_read_each_other_s_comparisons(self):
        # A lookup that ignored the parent id would hand back the other pair's
        # verdict, correctly formatted, with nothing failing anywhere.
        c = self.deploy()
        glsim.call(c, "register", CRITERION, "third item text", "fourth item text")
        self.mocks(rounds("a", "a"))
        glsim.call(c, "compare", 0)
        assert c.verdict(0) == "a"
        assert c.verdict(1) == ""
        assert c.stability(1)["comparisons"] == 0

    def test_the_stored_rounds_are_normalised_to_the_closed_vocabulary(self):
        # The model is free to answer "Item A". Storage is not: what lands on
        # chain is always one of a, b, neither. This is the part of the
        # re-derivation that is independently observable -- see DECISIONS.md on
        # the mutation that could not be caught.
        c = self.deploy()
        self.mocks(rounds("Item A", "first"))
        glsim.call(c, "compare", 0)
        stored = c.comparisons[0]
        assert stored.forward in ("a", "b", "neither")
        assert stored.reverse in ("a", "b", "neither")
        assert stored.forward == "a" and stored.reverse == "a"
        assert stored.verdict == "a"

    def test_the_verdict_never_contradicts_the_rounds_stored_beneath_it(self):
        # Defence in depth: with the honesty layer in place this can only fail
        # if BOTH defences are removed, which is what the paired mutation does.
        c = self.deploy()
        for f, r in [("a", "a"), ("b", "b"), ("a", "b"), ("neither", "b")]:
            self.mocks(rounds(f, r))
            glsim.call(c, "compare", 0)
            stored = c.comparisons[-1]
            assert stored.verdict == c._module.combine_rounds(
                stored.forward, stored.reverse
            )

    def test_a_leader_supplied_reason_is_sanitised_before_storage(self):
        c = self.deploy()
        self.mocks(rounds("a", "a", why_f="<script>x</script>\x00 clear tradeoff"))
        glsim.call(c, "compare", 0)
        stored = c.latest(0)["rounds"]["why_forward"]
        assert "<" not in stored and ">" not in stored and "\x00" not in stored
        assert "clear tradeoff" in stored

    def test_the_view_says_the_reasons_are_leader_supplied(self):
        c = self.deploy()
        self.mocks(rounds("a", "a"))
        glsim.call(c, "compare", 0)
        assert c.latest(0)["reasons_are_leader_supplied"] is True

    def test_the_author_is_recorded(self):
        glsim.set_mocks({})
        glsim.set_sender("0x" + "22" * 20)
        c = glsim.deploy(self.PATH)
        glsim.call(c, "register", CRITERION, ITEM_A, ITEM_B)
        assert c.pairs[0].author == "0x" + "22" * 20


class TestTiebreakRefusals(TiebreakBase):
    def test_a_short_criterion_is_refused(self):
        glsim.set_mocks({})
        c = glsim.deploy(self.PATH)
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "register", "too short", ITEM_A, ITEM_B)

    def test_an_over_long_criterion_is_refused(self):
        glsim.set_mocks({})
        c = glsim.deploy(self.PATH)
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "register", "x" * 301, ITEM_A, ITEM_B)

    def test_an_empty_item_is_refused(self):
        glsim.set_mocks({})
        c = glsim.deploy(self.PATH)
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "register", CRITERION, "", ITEM_B)

    def test_two_identical_items_are_refused(self):
        # There is nothing to compare, and a tie here would be meaningless.
        glsim.set_mocks({})
        c = glsim.deploy(self.PATH)
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "register", CRITERION, ITEM_A, ITEM_A)

    def test_an_over_long_item_is_refused(self):
        glsim.set_mocks({})
        c = glsim.deploy(self.PATH)
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "register", CRITERION, "x" * 601, ITEM_B)

    def test_a_read_with_a_nonexistent_id_is_a_user_error(self):
        c = self.deploy()
        with pytest.raises(gl.vm.UserError):
            c.verdict(9)

    def test_a_read_with_a_negative_id_does_not_return_the_last_record(self):
        # Python accepts -1 and returns the newest record. Nothing fails.
        c = self.deploy()
        with pytest.raises(gl.vm.UserError):
            c.verdict(-1)
        with pytest.raises(gl.vm.UserError):
            c.latest(-1)
        with pytest.raises(gl.vm.UserError):
            c.stability(-1)

    def test_a_view_is_safe_before_any_comparison(self):
        c = self.deploy()
        assert c.verdict(0) == ""
        assert c.latest(0)["compared"] is False
        assert c.stability(0)["comparisons"] == 0
        assert c.stability(0)["tied_pct"] == "0.0"

    def test_count_reflects_registrations(self):
        c = self.deploy()
        assert c.count() == 1
        glsim.call(c, "register", CRITERION, "another item", "yet another item")
        assert c.count() == 2


# ===========================================================================
# the harness itself must refuse what GenVM refuses
# ===========================================================================

class TestTheHarnessModelsGenVM:
    def test_a_collection_in_a_storage_dataclass_is_refused(self):
        from dataclasses import dataclass

        with pytest.raises(TypeError, match="cannot contain a collection"):
            @glsim.allow_storage
            @dataclass
            class Bad:
                rows: glsim.DynArray[str]

    def test_a_forbidden_storage_type_is_refused(self):
        from dataclasses import dataclass

        with pytest.raises(TypeError, match="not a valid storage type"):
            @glsim.allow_storage
            @dataclass
            class Bad:
                n: int

    def test_a_bare_generic_is_refused(self):
        # Bare TreeMap is rejected at deploy; it must be TreeMap[K, V]. On a
        # contract field this is the branch that fires, and it fires when the
        # contract is instantiated rather than when it is defined.
        class Bad(gl.Contract):
            rows: glsim.TreeMap

        with pytest.raises(TypeError, match="fully instantiated"):
            Bad()

    def test_a_builtin_container_on_a_contract_field_is_refused(self):
        class Bad(gl.Contract):
            rows: list

        with pytest.raises(TypeError, match="not a valid storage type"):
            Bad()

    def test_inmem_allocate_cannot_build_a_collection(self):
        with pytest.raises(TypeError, match="cannot build a storage collection"):
            gl.storage.inmem_allocate(glsim.DynArray[str])

    def test_a_dynarray_cannot_be_instantiated_directly(self):
        with pytest.raises(TypeError, match="can't be instantiated by user"):
            glsim.DynArray[str]()

    @pytest.mark.parametrize(
        "bad",
        [{"ok": True}, {"ok": {"nested": "x"}}, {"ok": ["a"]}, {"ok": 1}, "notadict"],
    )
    def test_the_block_boundary_refuses_anything_but_flat_strings(self, bad):
        with pytest.raises(TypeError):
            glsim.check_calldata_shape(bad)

    def test_a_flat_dict_of_str_passes_the_boundary(self):
        assert glsim.check_calldata_shape({"a": "1", "b": ""}) == {"a": "1", "b": ""}


# ===========================================================================
# Slate, executed
# ===========================================================================

SLATE_CRIT = "which proposal states its tradeoff most clearly"
FOUR = "alpha proposal|beta proposal|gamma proposal|delta proposal"
RANK_KEY = "Rank every item, best first"


def ranked(order, scores, why="because"):
    return {RANK_KEY: {"order": order, "scores": scores, "why": why}}


class SlateBase:
    PATH = str(CONTRACTS / "slate.py")

    def deploy(self, items=FOUR, closeness="2.0"):
        glsim.set_mocks({})
        glsim.set_sender("0x" + "11" * 20)
        c = glsim.deploy(self.PATH)
        glsim.call(c, "define", SLATE_CRIT, items, closeness)
        return c

    def mocks(self, prompts, v_prompts=None):
        glsim.set_mocks(prompts, v_prompts=v_prompts)


class TestSlateRanking(SlateBase):
    def test_a_clean_ranking_is_stored_in_rank_order(self):
        c = self.deploy()
        self.mocks(ranked([2, 0, 1, 3], [90.0, 70.0, 50.0, 10.0]))
        glsim.call(c, "rank", 0)
        assert c.order(0) == "2:1|0:2|1:3|3:4"

    def test_items_within_the_closeness_threshold_share_a_rank(self):
        c = self.deploy()
        self.mocks(ranked([2, 0, 1, 3], [88.0, 71.5, 70.9, 40.0]))
        glsim.call(c, "rank", 0)
        # 0 and 1 are 0.6 apart, inside a threshold of 2.0, so they tie.
        assert c.order(0) == "2:1|0:2|1:2|3:3"

    def test_the_placements_carry_the_item_text(self):
        c = self.deploy()
        self.mocks(ranked([2, 0, 1, 3], [90.0, 70.0, 50.0, 10.0]))
        glsim.call(c, "rank", 0)
        rows = c.latest(0)["placements"]
        assert [r["rank"] for r in rows] == [1, 2, 3, 4]
        assert rows[0]["item"] == "gamma proposal"
        assert rows[0]["band"] == 1

    def test_a_slate_where_everything_ties_is_a_finding_not_a_failure(self):
        c = self.deploy(closeness="50.0")
        self.mocks(ranked([0, 1, 2, 3], [90.0, 80.0, 70.0, 60.0]))
        glsim.call(c, "rank", 0)
        assert c.latest(0)["refusal"] == "undifferentiated"
        # Stored, not raised: the caller decides whether to rewrite the
        # criterion.
        assert c.latest(0)["ranked"] is True
        assert c.order(0) == "0:1|1:1|2:1|3:1"

    def test_a_discriminating_slate_is_not_marked_undifferentiated(self):
        c = self.deploy()
        self.mocks(ranked([0, 1, 2, 3], [90.0, 70.0, 50.0, 10.0]))
        glsim.call(c, "rank", 0)
        assert c.latest(0)["refusal"] == ""

    def test_the_slate_view_returns_the_frozen_definition(self):
        c = self.deploy()
        s = c.slate(0)
        assert s["criterion"] == SLATE_CRIT
        assert s["n_items"] == 4
        assert s["closeness"] == "2.0"
        assert s["items"][0] == "alpha proposal"


class TestSlateDivergentNodes(SlateBase):
    def test_two_nodes_swapping_a_tied_adjacent_pair_still_settle(self):
        # The exact failure that makes strict_eq on a raw ordering useless: two
        # honest validators swap two near-equal items roughly every time.
        c = self.deploy()
        self.mocks(
            ranked([2, 0, 1, 3], [88.0, 71.5, 70.9, 40.0]),
            v_prompts=ranked([2, 1, 0, 3], [88.0, 70.9, 71.5, 40.0]),
        )
        glsim.call(c, "rank", 0)
        assert glsim.RT.last_validator_verdict is True
        assert c.order(0) == "2:1|0:2|1:2|3:3"

    def test_two_nodes_reversing_the_top_two_do_not_settle(self):
        # The only part anyone cares about.
        c = self.deploy()
        self.mocks(
            ranked([0, 1, 2, 3], [90.0, 60.0, 40.0, 10.0]),
            v_prompts=ranked([1, 0, 2, 3], [90.0, 60.0, 40.0, 10.0]),
        )
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "rank", 0)
        assert len(c.rankings) == 0

    def test_a_leader_returning_a_non_permutation_is_rejected(self):
        c = self.deploy()
        self.mocks(ranked([0, 0, 1, 3], [90.0, 60.0, 40.0, 10.0]))
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "rank", 0)
        assert len(c.rankings) == 0

    def test_a_leader_returning_the_wrong_number_of_scores_is_rejected(self):
        c = self.deploy()
        self.mocks(ranked([0, 1, 2, 3], [90.0, 60.0, 40.0]))
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "rank", 0)

    def test_a_non_finite_score_is_rejected(self):
        c = self.deploy()
        self.mocks(ranked([0, 1, 2, 3], [90.0, 60.0, float("inf"), 10.0]))
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "rank", 0)

    def test_nothing_is_written_when_consensus_fails(self):
        c = self.deploy()
        self.mocks(
            ranked([0, 1, 2, 3], [90.0, 60.0, 40.0, 10.0]),
            v_prompts=ranked([3, 2, 1, 0], [90.0, 60.0, 40.0, 10.0]),
        )
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "rank", 0)
        assert len(c.rankings) == 0 and len(c.placements) == 0
        assert c.order(0) == ""


class TestSlateRefusals(SlateBase):
    def test_a_short_criterion_is_refused(self):
        glsim.set_mocks({})
        c = glsim.deploy(self.PATH)
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "define", "short", FOUR, "2.0")

    def test_fewer_than_two_items_is_refused(self):
        glsim.set_mocks({})
        c = glsim.deploy(self.PATH)
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "define", SLATE_CRIT, "only one", "2.0")

    def test_more_than_twelve_items_is_refused(self):
        glsim.set_mocks({})
        c = glsim.deploy(self.PATH)
        many = "|".join("item %d" % i for i in range(13))
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "define", SLATE_CRIT, many, "2.0")

    def test_duplicate_items_are_refused(self):
        glsim.set_mocks({})
        c = glsim.deploy(self.PATH)
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "define", SLATE_CRIT, "same|same", "2.0")

    @pytest.mark.parametrize("bad", ["", "abc", "nan", "inf", "-1"])
    def test_an_unusable_closeness_is_refused(self, bad):
        glsim.set_mocks({})
        c = glsim.deploy(self.PATH)
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "define", SLATE_CRIT, FOUR, bad)

    def test_a_nonexistent_or_negative_id_is_a_user_error(self):
        c = self.deploy()
        for bad in (9, -1):
            with pytest.raises(gl.vm.UserError):
                c.order(bad)
            with pytest.raises(gl.vm.UserError):
                c.latest(bad)
            with pytest.raises(gl.vm.UserError):
                c.slate(bad)

    def test_a_view_is_safe_before_any_ranking(self):
        c = self.deploy()
        assert c.order(0) == ""
        assert c.latest(0)["ranked"] is False
        assert c.count() == 1

    def test_two_slates_do_not_read_each_other_s_rankings(self):
        c = self.deploy()
        glsim.call(c, "define", SLATE_CRIT, "one thing|two thing", "1.0")
        self.mocks(ranked([0, 1, 2, 3], [90.0, 60.0, 40.0, 10.0]))
        glsim.call(c, "rank", 0)
        assert c.order(0) != ""
        assert c.order(1) == ""
        assert c.latest(1)["ranked"] is False


# ===========================================================================
# Cutline, executed
# ===========================================================================

CUT_CRIT = "which application shows the clearest measurable outcome"


class CutlineBase:
    PATH = str(CONTRACTS / "cutline.py")

    def deploy(self, k=2, on_tie="refuse", closeness="2.0", items=FOUR):
        glsim.set_mocks({})
        glsim.set_sender("0x" + "11" * 20)
        c = glsim.deploy(self.PATH)
        glsim.call(c, "define", CUT_CRIT, items, k, closeness, on_tie)
        return c

    def mocks(self, prompts, v_prompts=None):
        glsim.set_mocks(prompts, v_prompts=v_prompts)


class TestCutlineSelection(CutlineBase):
    def test_a_clean_boundary_selects_exactly_k(self):
        c = self.deploy(k=2)
        self.mocks(ranked([2, 0, 1, 3], [90.0, 70.0, 50.0, 10.0]))
        glsim.call(c, "select", 0)
        assert c.selected(0) == "0|2"
        assert c.latest(0)["cut_is_arbitrary"] is False

    def test_membership_is_sorted_so_the_order_inside_it_cannot_matter(self):
        c = self.deploy(k=2)
        self.mocks(ranked([3, 1, 0, 2], [90.0, 70.0, 50.0, 10.0]))
        glsim.call(c, "select", 0)
        assert c.selected(0) == "1|3"

    def test_refuse_selects_nobody_when_the_cut_falls_inside_a_tie(self):
        # Correct when K is a hard budget. Storing the attempt and marking it
        # is more useful than either picking arbitrarily or raising.
        c = self.deploy(k=2, on_tie="refuse")
        self.mocks(ranked([0, 1, 2, 3], [90.0, 89.0, 88.0, 10.0]))
        glsim.call(c, "select", 0)
        assert c.selected(0) == ""
        assert c.latest(0)["cut_is_arbitrary"] is True
        assert c.latest(0)["picks"] == []

    def test_expand_takes_the_whole_tied_band(self):
        # Correct when K is a target and fairness matters more than the count.
        c = self.deploy(k=2, on_tie="expand")
        self.mocks(ranked([0, 1, 2, 3], [90.0, 89.0, 88.0, 10.0]))
        glsim.call(c, "select", 0)
        assert c.selected(0) == "0|1|2"
        assert c.latest(0)["cut_is_arbitrary"] is False

    def test_the_policy_is_recorded_with_the_selection(self):
        c = self.deploy(k=2, on_tie="expand")
        self.mocks(ranked([0, 1, 2, 3], [90.0, 70.0, 50.0, 10.0]))
        glsim.call(c, "select", 0)
        assert c.latest(0)["on_tie"] == "expand"
        assert c.latest(0)["k"] == 2

    def test_the_picks_carry_the_item_text(self):
        c = self.deploy(k=2)
        self.mocks(ranked([2, 0, 1, 3], [90.0, 70.0, 50.0, 10.0]))
        glsim.call(c, "select", 0)
        picks = c.latest(0)["picks"]
        assert sorted(p["item"] for p in picks) == ["alpha proposal", "gamma proposal"]


class TestCutlineDivergentNodes(CutlineBase):
    def test_two_nodes_ordering_the_selected_pair_differently_still_settle(self):
        # The rung below Slate: who is in, not who is first. This pair of
        # results would fail Slate and must not fail Cutline.
        c = self.deploy(k=2)
        self.mocks(
            ranked([0, 1, 2, 3], [90.0, 80.0, 40.0, 10.0]),
            v_prompts=ranked([1, 0, 2, 3], [80.0, 90.0, 40.0, 10.0]),
        )
        glsim.call(c, "select", 0)
        assert glsim.RT.last_validator_verdict is True
        assert c.selected(0) == "0|1"

    def test_nodes_selecting_a_different_membership_do_not_settle(self):
        c = self.deploy(k=2)
        self.mocks(
            ranked([0, 1, 2, 3], [90.0, 80.0, 40.0, 10.0]),
            v_prompts=ranked([0, 2, 1, 3], [90.0, 80.0, 40.0, 10.0]),
        )
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "select", 0)
        assert len(c.selections) == 0

    def test_nodes_disagreeing_about_whether_the_cut_was_arbitrary_do_not_settle(self):
        c = self.deploy(k=2, on_tie="refuse")
        self.mocks(
            ranked([0, 1, 2, 3], [90.0, 89.0, 88.0, 10.0]),
            v_prompts=ranked([0, 1, 2, 3], [90.0, 80.0, 40.0, 10.0]),
        )
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "select", 0)

    def test_a_leader_returning_a_non_permutation_is_rejected(self):
        # Found by the mutation pass: the permutation guard in cutline had no
        # test of its own, only slate's.
        c = self.deploy(k=2)
        self.mocks(ranked([0, 0, 1, 3], [90.0, 60.0, 40.0, 10.0]))
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "select", 0)
        assert len(c.selections) == 0

    def test_a_leader_returning_the_wrong_number_of_scores_is_rejected(self):
        c = self.deploy(k=2)
        self.mocks(ranked([0, 1, 2, 3], [90.0, 60.0, 40.0]))
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "select", 0)


class TestCutlineRefusals(CutlineBase):
    @pytest.mark.parametrize("k", [0, 4, 9])
    def test_a_k_outside_the_item_count_is_refused(self, k):
        glsim.set_mocks({})
        c = glsim.deploy(self.PATH)
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "define", CUT_CRIT, FOUR, k, "2.0", "refuse")

    @pytest.mark.parametrize("policy", ["", "maybe", "REFUSE ALL", "expand-all"])
    def test_an_unknown_tie_policy_is_refused(self, policy):
        glsim.set_mocks({})
        c = glsim.deploy(self.PATH)
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "define", CUT_CRIT, FOUR, 2, "2.0", policy)

    def test_the_policy_is_case_insensitive(self):
        glsim.set_mocks({})
        c = glsim.deploy(self.PATH)
        glsim.call(c, "define", CUT_CRIT, FOUR, 2, "2.0", " Refuse ")
        assert c.latest(0)["on_tie"] == "refuse"

    def test_a_nonexistent_or_negative_id_is_a_user_error(self):
        c = self.deploy()
        for bad in (9, -1):
            with pytest.raises(gl.vm.UserError):
                c.selected(bad)
            with pytest.raises(gl.vm.UserError):
                c.latest(bad)

    def test_selected_is_empty_rather_than_raising_before_a_run(self):
        # One branch for a consuming contract instead of two.
        c = self.deploy()
        assert c.selected(0) == ""
        assert c.latest(0)["selected"] is False

    def test_two_cutlines_do_not_read_each_other_s_selections(self):
        c = self.deploy()
        glsim.call(c, "define", CUT_CRIT, "one thing|two thing", 1, "1.0", "refuse")
        self.mocks(ranked([0, 1, 2, 3], [90.0, 70.0, 50.0, 10.0]))
        glsim.call(c, "select", 0)
        assert c.selected(0) != ""
        assert c.selected(1) == ""


# ===========================================================================
# Winnow, executed
# ===========================================================================

WIN_STANDARD = "accept only items that name a measurable outcome"
TRIAGE_KEY = "Put every item in exactly one bucket"


def triaged(buckets, why=None):
    return {TRIAGE_KEY: {"buckets": buckets, "why": why or ["r"] * len(buckets)}}


class WinnowBase:
    PATH = str(CONTRACTS / "winnow.py")

    def deploy(self, max_review=50, items=FOUR):
        glsim.set_mocks({})
        glsim.set_sender("0x" + "11" * 20)
        c = glsim.deploy(self.PATH)
        glsim.call(c, "define", WIN_STANDARD, items, max_review)
        return c

    def mocks(self, prompts, v_prompts=None):
        glsim.set_mocks(prompts, v_prompts=v_prompts)


class TestWinnowPartition(WinnowBase):
    def test_a_partition_is_stored_in_item_order(self):
        c = self.deploy()
        self.mocks(triaged(["accept", "reject", "review", "accept"]))
        glsim.call(c, "triage", 0)
        assert c.partition(0) == "accept|reject|review|accept"

    def test_an_unrecognised_label_lands_in_review(self):
        # The safe direction: an unreadable label goes to a human rather than
        # silently accepting or discarding the item.
        c = self.deploy()
        self.mocks(triaged(["accept", "banana", "reject", "accept"]))
        glsim.call(c, "triage", 0)
        assert c.partition(0) == "accept|review|reject|accept"

    def test_bucket_returns_one_item_for_a_consuming_contract(self):
        c = self.deploy()
        self.mocks(triaged(["accept", "reject", "review", "accept"]))
        glsim.call(c, "triage", 0)
        assert c.bucket(0, 0) == "accept"
        assert c.bucket(0, 2) == "review"

    def test_the_labels_carry_item_text_and_a_reason(self):
        c = self.deploy()
        self.mocks(
            triaged(["accept", "reject", "review", "accept"],
                    why=["names a number", "no outcome", "unclear", "has metrics"])
        )
        glsim.call(c, "triage", 0)
        rows = c.latest(0)["labels"]
        assert rows[1]["item"] == "beta proposal"
        assert rows[1]["bucket"] == "reject"
        assert rows[1]["why"] == "no outcome"

    def test_a_reason_is_sanitised_before_storage(self):
        c = self.deploy()
        self.mocks(
            triaged(["accept", "reject", "review", "accept"],
                    why=["<b>x</b>\x00 fine", "r", "r", "r"])
        )
        glsim.call(c, "triage", 0)
        stored = c.latest(0)["labels"][0]["why"]
        assert "<" not in stored and "\x00" not in stored and "fine" in stored


class TestWinnowAgreement(WinnowBase):
    def test_one_item_drifting_through_review_still_settles(self):
        # An item genuinely near a boundary can honestly land either side. That
        # is the standard working, not a disagreement about the standard.
        c = self.deploy()
        self.mocks(
            triaged(["accept", "reject", "review", "accept"]),
            v_prompts=triaged(["accept", "reject", "accept", "accept"]),
        )
        glsim.call(c, "triage", 0)
        assert glsim.RT.last_validator_verdict is True

    def test_two_items_drifting_does_not_settle(self):
        c = self.deploy()
        self.mocks(
            triaged(["review", "review", "accept", "accept"]),
            v_prompts=triaged(["accept", "reject", "accept", "accept"]),
        )
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "triage", 0)

    def test_an_item_flipping_accept_to_reject_never_settles(self):
        # Nothing near a boundary crosses two buckets at once. Forgiving this
        # would let two nodes disagree about whether an item passes and still
        # produce a record that looks decisive.
        c = self.deploy()
        self.mocks(
            triaged(["accept", "reject", "review", "accept"]),
            v_prompts=triaged(["reject", "reject", "review", "accept"]),
        )
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "triage", 0)
        assert len(c.triages) == 0

    def test_nothing_is_written_when_consensus_fails(self):
        c = self.deploy()
        self.mocks(
            triaged(["accept", "accept", "accept", "accept"]),
            v_prompts=triaged(["reject", "reject", "reject", "reject"]),
        )
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "triage", 0)
        assert len(c.triages) == 0 and len(c.labels) == 0
        assert c.partition(0) == ""

    @pytest.mark.parametrize("buckets", [["accept", "reject"],
                                         ["accept"] * 5,
                                         []])
    def test_a_leader_labelling_the_wrong_number_of_items_is_rejected(self, buckets):
        # Found by the mutation pass: every test fed exactly the right number
        # of labels, so the count guard had nothing asserting it.
        c = self.deploy()
        self.mocks(triaged(buckets))
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "triage", 0)
        assert len(c.triages) == 0


class TestWinnowRefusals(WinnowBase):
    def test_a_batch_mostly_in_review_is_marked_too_vague(self):
        # A standard that sends most of a batch to a human has not triaged it,
        # and the contract says so rather than handing back a pile of work.
        c = self.deploy(max_review=50)
        self.mocks(triaged(["review", "review", "review", "accept"]))
        glsim.call(c, "triage", 0)
        assert c.latest(0)["refusal"] == "standard_too_vague"
        # Still stored: the caller decides whether to rewrite the standard.
        assert c.latest(0)["triaged"] is True
        assert c.partition(0) == "review|review|review|accept"

    def test_a_batch_inside_the_declared_fraction_is_not_marked(self):
        c = self.deploy(max_review=50)
        self.mocks(triaged(["review", "accept", "reject", "accept"]))
        glsim.call(c, "triage", 0)
        assert c.latest(0)["refusal"] == ""

    def test_exactly_at_the_threshold_is_allowed(self):
        c = self.deploy(max_review=50)
        self.mocks(triaged(["review", "review", "accept", "reject"]))
        glsim.call(c, "triage", 0)
        assert c.latest(0)["refusal"] == ""

    @pytest.mark.parametrize("pct", [101, 200])
    def test_a_percentage_outside_zero_to_a_hundred_is_refused(self, pct):
        glsim.set_mocks({})
        c = glsim.deploy(self.PATH)
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "define", WIN_STANDARD, FOUR, pct)

    def test_a_short_standard_is_refused(self):
        glsim.set_mocks({})
        c = glsim.deploy(self.PATH)
        with pytest.raises(gl.vm.UserError):
            glsim.call(c, "define", "short", FOUR, 50)

    def test_a_nonexistent_or_negative_id_is_a_user_error(self):
        c = self.deploy()
        for bad in (9, -1):
            with pytest.raises(gl.vm.UserError):
                c.partition(bad)
            with pytest.raises(gl.vm.UserError):
                c.latest(bad)
            with pytest.raises(gl.vm.UserError):
                c.bucket(bad, 0)

    def test_a_negative_item_index_is_refused(self):
        c = self.deploy()
        with pytest.raises(gl.vm.UserError):
            c.bucket(0, -1)
        with pytest.raises(gl.vm.UserError):
            c.bucket(0, 99)

    def test_views_are_safe_before_any_triage(self):
        c = self.deploy()
        assert c.partition(0) == ""
        assert c.bucket(0, 0) == ""
        assert c.latest(0)["triaged"] is False

    def test_two_batches_do_not_read_each_other_s_triages(self):
        c = self.deploy()
        glsim.call(c, "define", WIN_STANDARD, "one thing|two thing", 50)
        self.mocks(triaged(["accept", "reject", "review", "accept"]))
        glsim.call(c, "triage", 0)
        assert c.partition(0) != ""
        assert c.partition(1) == ""
        assert c.bucket(1, 0) == ""
