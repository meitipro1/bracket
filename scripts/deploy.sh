#!/usr/bin/env bash
#
# deploy.sh — lint, deploy and EXERCISE all four contracts.
#
#   ./scripts/deploy.sh studionet
#
# A contract page showing only a deploy transaction proves the file compiles and
# nothing else. This script deploys AND calls each contract, so the explorer
# shows real method calls with the leader's proposal and the validators' votes
# beside them. That page is the strongest single artifact in a submission.
#
# For each contract it runs one call that SUCCEEDS and one that REFUSES: a tied
# pair, an undifferentiated slate, a cut inside a tie, a batch too vague to
# triage. Refusing is what these primitives are for, and a page showing only
# successes is the weaker demonstration.
#
# Deployment can also be done entirely by hand through the Studio web interface
# at studio.genlayer.com, which is the recommended route: paste the contract,
# deploy, and call the methods through the form. Never put a private key into a
# file or hand one to a tool.
#
# Requires: npm i -g genlayer

set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

NETWORK="${1:-studionet}"
gold() { printf '\033[33m%s\033[0m\n' "$*"; }
dim()  { printf '\033[2m%s\033[0m\n'  "$*"; }

# `network` is a command group, not a value: `genlayer network studionet`
# answers "unknown command" and exits 1, which under `set -e` kills the script
# on its first line.
genlayer network set "$NETWORK"

# genvm-lint needs its subcommand, and utf-8 stdout: the linter prints a U+2713
# tick on success and dies encoding it under the cp1252 stdout Windows hands a
# child process, reporting a PASSING contract as failed.
lint() { PYTHONIOENCODING=utf-8 genvm-lint lint "$1"; }

# --args is variadic. A JSON array is ONE argument, not the argument list, so
# `--args '[0]'` passes an array where the method wanted an integer.
deploy() {
  genlayer deploy --contract "$1" | grep -oE '0x[0-9a-fA-F]{40}' | head -1
}

CRITERION="which explains the tradeoff more clearly"
# Real sentences, not placeholders. Four labels with no content give the model
# nothing to judge, so it scores them differently on every run, the bands differ
# between nodes and rank() never settles. That cost three failed transactions
# before the demo data was rewritten -- see DECISIONS.md.
PROPOSALS="Cuts latency by 40 percent, at the cost of 2x memory per node.|Improves throughput; some additional resource usage is expected.|A faster, more scalable and more reliable pipeline for everyone.|Best-in-class performance with no downsides worth mentioning."
OUTCOMES="Cut support tickets from 120 to 38 per week over two months.|Reduced onboarding time; teams reported it felt faster.|A modern platform that helps teams work better together.|Response time dropped from 4.2 seconds to 0.9 seconds."

# ---------------------------------------------------------------------------
gold "Tiebreak"
dim  "linting"
lint contracts/tiebreak.py
TB=$(deploy contracts/tiebreak.py)
gold "  deployed at $TB"

dim "  register() a pair that a criterion should separate"
genlayer write "$TB" register --args \
  "$CRITERION" \
  "A short note that states the tradeoff and gives one worked example." \
  "A longer note that lists benefits and never mentions a cost." >/dev/null

dim "  compare()  both presentation orders, one block"
genlayer write "$TB" compare --args 0
genlayer call  "$TB" latest  --args 0

dim "  register() a pair the criterion cannot separate, for the refusal"
genlayer write "$TB" register --args \
  "$CRITERION" \
  "A note of moderate length that is broadly reasonable about the subject." \
  "Another note of moderate length that is broadly reasonable as well." >/dev/null
genlayer write "$TB" compare   --args 1 || true
genlayer call  "$TB" stability --args 1

# ---------------------------------------------------------------------------
gold "Slate"
dim  "linting"
lint contracts/slate.py
SL=$(deploy contracts/slate.py)
gold "  deployed at $SL"

dim "  define() a slate with a tight threshold, so ranks separate"
genlayer write "$SL" define --args \
  "which proposal states its tradeoff most clearly" "$PROPOSALS" "8.0" >/dev/null
dim "  rank()   order, band, agree, store"
genlayer write "$SL" rank  --args 0
genlayer call  "$SL" order --args 0

dim "  define() a slate with a huge threshold, to put undifferentiated on chain"
genlayer write "$SL" define --args \
  "which proposal states its tradeoff most clearly" "$PROPOSALS" "1000" >/dev/null
genlayer write "$SL" rank   --args 1 || true
genlayer call  "$SL" latest --args 1

# ---------------------------------------------------------------------------
gold "Cutline"
dim  "linting"
lint contracts/cutline.py
CU=$(deploy contracts/cutline.py)
gold "  deployed at $CU"

dim "  define() a clean cut, k of 2"
genlayer write "$CU" define --args \
  "which application shows the clearest measurable outcome" "$OUTCOMES" 2 "8.0" "refuse" >/dev/null
genlayer write "$CU" select   --args 0
genlayer call  "$CU" selected --args 0

dim "  define() a cut that can fall inside a tie, to put the refusal on chain"
genlayer write "$CU" define --args \
  "which application shows the clearest measurable outcome" "$OUTCOMES" 2 "1000" "refuse" >/dev/null
genlayer write "$CU" select --args 1 || true
genlayer call  "$CU" latest --args 1

# ---------------------------------------------------------------------------
gold "Winnow"
dim  "linting"
lint contracts/winnow.py
WI=$(deploy contracts/winnow.py)
gold "  deployed at $WI"

dim "  define() a batch with a workable review ceiling"
genlayer write "$WI" define --args \
  "accept only items that name a measurable outcome" "$OUTCOMES" 50 >/dev/null
genlayer write "$WI" triage    --args 0
genlayer call  "$WI" partition --args 0

dim "  define() a batch with zero tolerance, to put standard_too_vague on chain"
genlayer write "$WI" define --args \
  "accept only items that are broadly quite good in some way" "$OUTCOMES" 0 >/dev/null
genlayer write "$WI" triage --args 1 || true
genlayer call  "$WI" latest --args 1

cat <<EOF

  Tiebreak  $TB
  Slate     $SL
  Cutline   $CU
  Winnow    $WI

  Explorer  https://explorer-studio.genlayer.com/address/<address>

Open each page before submitting. Every one must show a Deploy transaction AND
at least one method call with a Consensus Result beside it.

EOF
