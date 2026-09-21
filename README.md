# Verdict

A decision language for regulated logic. A decision compiles only if it can
explain itself.

Part of the [Kinode](../kinode-stack) stack. Lowers to [Canon](../canon), so
verification, capability analysis, journaling and the promotion gate apply
unchanged.

## Install

```sh
pip install -e .
```

## A decision

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

## What is enforced at compile time

**Every rule states a reason.** Omitting `because` is a parse error, not a lint
warning.

**Every decision has a default.** There is no input the decision cannot answer
and no outcome without a recorded reason.

**Every factor states why it is used.** A factor that cannot appear in an
explanation is not usable in a regulated decision.

**Prohibited factors are unreachable, not merely unused.** A field named in
`prohibited` is rejected whether a rule reads it directly or reaches it through
a factor, and the diagnostic names the route:

```
error[CANON-E0903]: rule 'below_credit_floor' depends on a prohibited field
  fields: ['input.applicant.legal_name']
  via_factors: ['tenure']
  note: A prohibited field reached through a factor is still a prohibited field.
```

## What it produces

For `decision assess(...) -> Ruling`, Verdict generates:

- `record AssessResult { outcome: Ruling, reasons: List<Reason>, factors: List<Factor> }`
  with an invariant that a result always carries at least one reason
- `fn assess(...) -> AssessResult` — rules evaluated in written order
- `fn assess_outcome(...) -> Ruling` — the outcome without the reasoning
- contracts asserting every result carries a reason and reports every factor
  considered, plus the `explains` and `deterministic` laws

At runtime every decision carries its reasoning:

```
Decline: "The credit score is below the published floor of 560."
factors: score=400 (w45), burden=2 (w35), tenure=120 (w20)
```

## Usage

```python
from verdict import parse_verdict
from canon.checker import check

mod, bag = parse_verdict(open("underwriting.verdict").read(), "underwriting.verdict")
cr = check([mod], bag)
```

Or through the command line, which dispatches on extension:

```sh
canon check underwriting.verdict
canon verify underwriting.verdict --runs 60
```

## Tests

```sh
python tests/smoke_verdict.py
```

## Licence

Apache-2.0. Copyright Kinode.
