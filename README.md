# Verdict

decision language for regulated logic. a decision will not compile unless it can
explain itself.

part of [kinode](https://github.com/KinodeLLC/kinode-stack). lowers to [canon](https://github.com/KinodeLLC/canon) so verification,
capability analysis, journaling and the promotion gate already work on it.

## install

```sh
pip install -e .
```

## example

```verdict
module underwriting

decision assess(input: Assessment) -> Ruling
  intent "Decide a personal loan on credit quality, affordability and tenure."
  cost steps 200000

  prohibited input.applicant.legal_name, input.applicant.email

  factor score: Int = Int.max(input.bureau_score, input.applicant.credit_score)
    because "Credit history is the strongest single predictor of repayment."
    weight 45

  factor burden: Int = affordability_ratio(input.request.amount_requested,
                                           input.applicant.annual_income)
    because "Borrowing as a share of income bounds what the applicant can afford."
    weight 35

  rule below_credit_floor
    when score < 560
    outcome Decline
    because "The credit score is below the published floor of 560."

  rule prime
    when score >= 720 and burden <= 30
    outcome Approve
    because "Strong credit and affordable borrowing."

  otherwise Refer
    because "Does not meet the published criteria for an automatic decision."
```

## constraints

every rule needs a `because` on it. leave it off and you get a parse error, not
a warning you can ignore, because a decision you cannot explain to the person
it was made about is not usable

every decision needs an `otherwise`. without one there are inputs the decision
cannot answer at all and outcomes with nothing recorded about why

every factor needs a `because` too. a factor that cannot go in the explanation
is no use to you in a regulated decision

prohibited fields are unreachable, not just unused. it does not matter whether a
rule reads the field directly or gets at it through a factor, both get rejected
and the error tells you which route it took

```
error[CANON-E0903]: rule 'below_credit_floor' depends on a prohibited field
  fields: ['input.applicant.legal_name']
  via_factors: ['tenure']
```

## output

`decision assess(...) -> Ruling` gives you

| generated | what it is |
| --- | --- |
| `record AssessResult` | outcome, reasons, factors, with an invariant that there is always at least one reason |
| `fn assess(...)` | rules run in the order you wrote them |
| `fn assess_outcome(...)` | just the outcome if you do not want the reasoning |
| contracts | every result carries a reason and reports every factor, plus the `explains` and `deterministic` laws |

at runtime the reasoning comes back with it

```
Decline: "The credit score is below the published floor of 560."
factors: score=400 (w45), burden=2 (w35), tenure=120 (w20)
```

## usage

```python
from verdict import parse_verdict
from canon.checker import check

mod, bag = parse_verdict(open("underwriting.verdict").read(), "underwriting.verdict")
cr = check([mod], bag)
```

or through the cli, it goes by extension

```sh
canon check underwriting.verdict
canon verify underwriting.verdict --runs 60
```

## tests

```sh
python tests/smoke_verdict.py
```

## licence

Apache-2.0, Kinode.
