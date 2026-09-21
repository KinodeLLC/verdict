"""Verdict: lowering, reason trees, and prohibited-factor enforcement."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "canon" / "src"))
sys.path.insert(0, str(ROOT / "verdict" / "src"))

from canon import Hasher, format_module  # noqa: E402
from canon import values as V  # noqa: E402
from canon.checker import check  # noqa: E402
from canon.interp import Budget, Interpreter  # noqa: E402
from canon.ledger import Ledger  # noqa: E402
from canon.verifier import Verifier  # noqa: E402
from verdict import parse_verdict  # noqa: E402

SRC = r'''
module underwriting

enum Ruling {
  | Approve
  | Refer
  | Decline
}

record Application {
  applicant_id: Text
  credit_score: Int
  annual_income: Int
  requested: Int
  months_employed: Int
  postcode: Text
  classify postcode personal
  classify applicant_id pseudonymous
  invariant annual_income >= 0
  invariant requested >= 0
  invariant credit_score >= 0
  invariant months_employed >= 0
}

decision assess(app: Application) -> Ruling
  intent "Decide a personal loan application on credit, affordability and tenure."
  prohibited app.postcode

  factor score: Int = app.credit_score
    because "Credit history is the strongest single predictor of repayment."
    weight 40

  factor burden: Int = Option.unwrap_or(Int.div(app.requested * 100, Int.max(app.annual_income, 1)), 100)
    because "Borrowing as a share of income bounds what the applicant can afford."
    weight 35

  factor tenure: Int = app.months_employed
    because "Length of employment is a proxy for income stability."
    weight 25

  rule thin_file
    when score < 500
    outcome Decline
    because "Credit score is below the published minimum of 500."

  rule overextended
    when burden > 45
    outcome Decline
    because "The requested amount exceeds 45 percent of annual income."

  rule prime
    when score >= 720 and burden <= 30 and tenure >= 12
    outcome Approve
    because "Strong credit, affordable borrowing and stable employment."

  otherwise Refer
    because "Does not meet the published criteria for an automatic decision."
'''

# Reads a prohibited field directly inside a rule.
DIRECT = SRC.replace(
    "    when score < 500\n",
    "    when score < 500 and app.postcode != \"SW1\"\n")

# Reads a prohibited field through a factor, which must be caught the same way.
INDIRECT = SRC.replace(
    "  factor tenure: Int = app.months_employed\n",
    "  factor tenure: Int = Text.length(app.postcode)\n")

# A rule with no stated reason.
NO_REASON = SRC.replace(
    '    outcome Decline\n    because "Credit score is below the published minimum of 500."\n',
    "    outcome Decline\n")

# No default outcome.
NO_DEFAULT = SRC.replace(
    '  otherwise Refer\n    because "Does not meet the published criteria for an automatic decision."\n',
    "")


def build(src, label="underwriting"):
    mod, bag = parse_verdict(src, f"{label}.verdict")
    if bag.has_errors:
        return None, bag
    res = check([mod], bag)
    return res, res.bag


def app(score=700, income=60000, requested=15000, months=24, postcode="SW1A"):
    return V.Record("Application", (
        ("applicant_id", "a-1"), ("credit_score", score),
        ("annual_income", income), ("requested", requested),
        ("months_employed", months), ("postcode", postcode)))


def main():
    failures = []

    def case(name, fn):
        try:
            print(f"  ok    {name}: {fn()}")
        except AssertionError as ae:
            failures.append(name)
            print(f"  FAIL  {name}: {ae}")

    res, bag = build(SRC)
    if res is None or bag.has_errors:
        print(bag.render(SRC))
        return 1

    print("lowering")

    def t_lowered():
        names = sorted(res.env.fns)
        types = sorted(res.env.types)
        assert "underwriting.assess" in names, names
        assert "underwriting.assess_outcome" in names, names
        assert "AssessResult" in types and "Reason" in types \
            and "Factor" in types, types
        return f"generated {len(names)} functions and AssessResult/Reason/Factor"
    case("a decision lowers to a Canon function and result type", t_lowered)

    def t_contracts():
        fi = res.env.fns["underwriting.assess"]
        assert len(fi.decl.ensures) >= 2, fi.decl.ensures
        laws = [l.name for l in fi.decl.laws]
        assert "explains" in laws and "deterministic" in laws, laws
        return f"ensures={len(fi.decl.ensures)}, laws={laws}"
    case("the generated function carries explainability contracts", t_contracts)

    def t_canonical():
        text = format_module(res.modules[0])
        assert "fn assess(app: Application) -> AssessResult" in text, text[:400]
        assert "record AssessResult" in text
        return f"renders as {len(text.splitlines())} lines of canonical Canon"
    case("the lowered module renders as ordinary Canon", t_canonical)

    print("\nreason trees")

    def run(a):
        led = Ledger()
        led.broker.grant("test", ["*"], reason="smoke test")
        it = Interpreter(res, led, Budget())
        return it.call("assess", [a])

    def t_decline_thin():
        r = run(app(score=420))
        assert r.get("outcome").ctor == "Decline", V.show(r.get("outcome"))
        reasons = r.get("reasons")
        assert len(reasons) == 1
        basis = reasons[0].get("basis")
        assert "minimum of 500" in basis, basis
        return f"Decline: {basis}"
    case("a decline carries the rule that produced it", t_decline_thin)

    def t_approve():
        r = run(app(score=760, income=100000, requested=20000, months=36))
        assert r.get("outcome").ctor == "Approve", V.show(r.get("outcome"))
        return f"Approve: {r.get('reasons')[0].get('basis')[:44]}..."
    case("an approval carries its reason", t_approve)

    def t_default():
        r = run(app(score=650, income=60000, requested=15000, months=6))
        assert r.get("outcome").ctor == "Refer", V.show(r.get("outcome"))
        assert "automatic decision" in r.get("reasons")[0].get("basis")
        return "Refer with the default reason"
    case("an input matching no rule reaches the default with a reason",
         t_default)

    def t_factors():
        r = run(app(score=700, income=60000, requested=15000, months=24))
        factors = r.get("factors")
        assert len(factors) == 3, len(factors)
        names = [f.get("name") for f in factors]
        assert names == ["score", "burden", "tenure"], names
        weights = sum(f.get("weight") for f in factors)
        assert weights == 100, weights
        rendered = ", ".join(f"{f.get('name')}={f.get('value')}"
                             for f in factors)
        assert all(f.get("basis") for f in factors), "a factor has no basis"
        return f"{rendered} (weights sum to {weights})"
    case("every factor is reported with its value, weight and basis",
         t_factors)

    def t_rule_order():
        # An applicant who trips both decline rules must be told about the
        # first one, deterministically -- not whichever happened to be checked.
        a = run(app(score=400, income=10000, requested=9000, months=1))
        b = run(app(score=400, income=10000, requested=9000, months=1))
        assert a.get("reasons")[0].get("rule") == "thin_file"
        assert V.compare(a, b) == 0
        return "first matching rule wins, stably"
    case("rules are evaluated in written order", t_rule_order)

    print("\nprohibited factors")

    def t_direct():
        r, b = build(DIRECT)
        assert b.has_errors, "a direct read of a prohibited field compiled"
        d = next(x for x in b if x.code == "CANON-E0903")
        assert "app.postcode" in d.facts.get("fields", []), d.facts
        return f"{d.code}: {d.message}"
    case("a rule reading a prohibited field is rejected", t_direct)

    def t_indirect():
        r, b = build(INDIRECT)
        assert b.has_errors, "a prohibited field reached via a factor compiled"
        ds = [x for x in b if x.code == "CANON-E0903"]
        assert ds, [x.code for x in b]
        via = [x for x in ds if x.facts.get("via_factors")]
        assert via, "the factor route was not reported"
        return (f"blocked at factor {ds[0].facts.get('factor')!r} and at "
                f"rule via {via[0].facts['via_factors']}")
    case("a prohibited field reached through a factor is rejected",
         t_indirect)

    print("\nstructural requirements")

    def t_no_reason():
        r, b = build(NO_REASON)
        assert b.has_errors, "a rule without a reason compiled"
        d = next(x for x in b if "does not state a reason" in x.message)
        return d.message
    case("a rule with no stated reason does not compile", t_no_reason)

    def t_no_default():
        r, b = build(NO_DEFAULT)
        assert b.has_errors, "a decision without a default compiled"
        d = next(x for x in b if x.code == "CANON-E0305")
        return d.message
    case("a decision with no default outcome does not compile", t_no_default)

    print("\nverification")

    def t_verify():
        hashes = {qn: di.hash
                  for qn, di in Hasher().add_modules(res.modules).items()}
        v = Verifier(res, seed="kinode", runs=40, hashes=hashes)
        rep = v.verify_all(only=["underwriting.assess"])
        f = rep.functions[0]
        assert f.ok, [c.to_json() for c in f.counterexamples]
        return (f"{f.passed}/{f.runs} generated applications produced a "
                f"reasoned outcome")
    case("the generated decision passes verification", t_verify)

    print("\nRESULT:", "pass" if not failures else f"FAIL ({failures})")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
