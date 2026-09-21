"""Integration tests, run against GenLayer Studio with gltest.

    pip install genlayer-test
    gltest --network studionet tests/test_integration.py

These are slower than the other two suites and they prove something different:
that each contract deploys, that storage round-trips, that the deterministic
gates fire, and that the whole leader-plus-validator cycle completes against a
real runtime rather than against tests/glsim.py.

The model is mocked, so a run is deterministic and needs no inference budget.
Mocks match by substring against the message the runtime builds, so the keys
below are fragments of the prompts in contracts/.
"""

import pytest

# gltest is only needed for this file. Skip cleanly when it is absent so that
# `pytest tests/` works out of the box on a machine with nothing installed but
# pytest, and still runs everything in test_logic.py and test_e2e.py.
gltest = pytest.importorskip(
    "gltest",
    reason="integration tests need genlayer-test and a running Studio: "
           "pip install genlayer-test, then gltest --network studionet",
)
from gltest import get_contract_factory                      # noqa: E402
from gltest.assertions import tx_execution_succeeded         # noqa: E402


CRITERION = "which explains the tradeoff more clearly"
ITEM_A = "A short note that states the tradeoff and gives one worked example."
ITEM_B = "A longer note that lists benefits and never mentions a cost."

FOUR = "alpha proposal|beta proposal|gamma proposal|delta proposal"
SLATE_CRIT = "which proposal states its tradeoff most clearly"
WIN_STANDARD = "accept only items that name a measurable outcome"


def llm(mapping):
    """Build a mocked prompt response table keyed by prompt substring."""
    return {"nondet_exec_prompt": mapping}


class TestTiebreak:
    @pytest.fixture
    def contract(self):
        factory = get_contract_factory(contract_file_path="tiebreak.py")
        return factory.deploy(args=[])

    def test_a_pair_registers_and_compares(self, contract):
        tx = contract.register(args=[CRITERION, ITEM_A, ITEM_B])
        assert tx_execution_succeeded(tx)
        assert contract.count(args=[]) == 1

    def test_a_view_is_safe_before_any_comparison(self, contract):
        contract.register(args=[CRITERION, ITEM_A, ITEM_B])
        assert contract.verdict(args=[0]) == ""
        assert contract.stability(args=[0])["comparisons"] == 0

    def test_a_short_criterion_is_refused(self, contract):
        with pytest.raises(Exception):
            contract.register(args=["short", ITEM_A, ITEM_B])

    def test_an_unknown_pair_is_refused(self, contract):
        contract.register(args=[CRITERION, ITEM_A, ITEM_B])
        with pytest.raises(Exception):
            contract.verdict(args=[9])


class TestSlate:
    @pytest.fixture
    def contract(self):
        factory = get_contract_factory(contract_file_path="slate.py")
        return factory.deploy(args=[])

    def test_a_slate_defines_and_stores_its_items(self, contract):
        tx = contract.define(args=[SLATE_CRIT, FOUR, "2.0"])
        assert tx_execution_succeeded(tx)
        s = contract.slate(args=[0])
        assert s["n_items"] == 4
        assert s["closeness"] == "2.0"

    def test_a_view_is_safe_before_any_ranking(self, contract):
        contract.define(args=[SLATE_CRIT, FOUR, "2.0"])
        assert contract.order(args=[0]) == ""

    def test_an_unusable_closeness_is_refused(self, contract):
        with pytest.raises(Exception):
            contract.define(args=[SLATE_CRIT, FOUR, "nan"])


class TestCutline:
    @pytest.fixture
    def contract(self):
        factory = get_contract_factory(contract_file_path="cutline.py")
        return factory.deploy(args=[])

    def test_a_cutline_defines_with_its_tie_policy(self, contract):
        tx = contract.define(args=["which application shows the clearest outcome",
                                   FOUR, 2, "2.0", "refuse"])
        assert tx_execution_succeeded(tx)
        assert contract.latest(args=[0])["on_tie"] == "refuse"

    def test_an_unknown_tie_policy_is_refused(self, contract):
        with pytest.raises(Exception):
            contract.define(args=["which application shows the clearest outcome",
                                  FOUR, 2, "2.0", "maybe"])

    def test_selected_is_empty_rather_than_raising_before_a_run(self, contract):
        contract.define(args=["which application shows the clearest outcome",
                              FOUR, 2, "2.0", "refuse"])
        assert contract.selected(args=[0]) == ""


class TestWinnow:
    @pytest.fixture
    def contract(self):
        factory = get_contract_factory(contract_file_path="winnow.py")
        return factory.deploy(args=[])

    def test_a_batch_defines_with_its_review_ceiling(self, contract):
        tx = contract.define(args=[WIN_STANDARD, FOUR, 50])
        assert tx_execution_succeeded(tx)
        assert contract.latest(args=[0])["max_review_pct"] == 50

    def test_a_percentage_above_a_hundred_is_refused(self, contract):
        with pytest.raises(Exception):
            contract.define(args=[WIN_STANDARD, FOUR, 200])

    def test_views_are_safe_before_any_triage(self, contract):
        contract.define(args=[WIN_STANDARD, FOUR, 50])
        assert contract.partition(args=[0]) == ""
        assert contract.bucket(args=[0, 0]) == ""
