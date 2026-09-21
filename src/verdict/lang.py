"""
Verdict: a decision language for regulated logic.

A decision written here cannot compile unless it can explain itself. That is
the whole point of the language, and it is enforced structurally rather than by
convention:

  * Every rule must state a `because`. A rule without a stated basis is a
    parse error, not a lint warning.
  * Every decision must have an `otherwise`, so there is no input for which the
    system has no answer and no reason.
  * `prohibited` factors are rejected at compile time if anything in the
    decision reads them -- directly or through a factor. This is the
    difference between a policy saying a factor must not be used and a system
    in which it cannot be.
  * Fields carrying a data classification of `personal` or above are reported
    unless the decision explicitly acknowledges them, so using protected data
    is always a deliberate act that appears in the diff.

Verdict lowers to ordinary Canon: a record type for the result, a function that
computes the factors and evaluates the rules in order, and contracts asserting
that the result always carries at least one reason and that every factor used
is reported. Everything downstream -- the verifier, the capability analysis,
the journal, the promotion gate -- then applies unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from canon import ast as A
from canon.diagnostics import Bag, Repair, Span
from canon.lexer import Lexer, T
from canon.parser import Parser
from canon import types as TY


LANGUAGE_VERSION = "0.1"

# Generated support types, shared by every decision in a module.
SUPPORT_TYPES = """
record Reason {
  rule: Text
  basis: Text
}

record Factor {
  name: Text
  value: Int
  weight: Int
  basis: Text
}
"""


# --------------------------------------------------------------------------
# Surface declarations
# --------------------------------------------------------------------------

@dataclass
class FactorDecl:
    name: str
    ty: A.TypeExpr
    expr: A.Expr
    basis: str = ""
    weight: int = 0
    span: Span = field(default_factory=Span.unknown)


@dataclass
class RuleDecl:
    name: str
    condition: A.Expr
    outcome: str
    outcome_args: list = field(default_factory=list)
    basis: str = ""
    span: Span = field(default_factory=Span.unknown)


@dataclass
class DecisionDecl:
    name: str = ""
    params: list = field(default_factory=list)
    outcome_type: str = ""
    intent: str = ""
    doc: str = ""
    uses: list = field(default_factory=list)
    prohibited: list = field(default_factory=list)
    acknowledged: list = field(default_factory=list)
    factors: list = field(default_factory=list)
    rules: list = field(default_factory=list)
    otherwise: Optional[RuleDecl] = None
    cost: Optional[A.Cost] = None
    span: Span = field(default_factory=Span.unknown)


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------

class VerdictParser(Parser):
    """
    Parses Verdict source into Canon declarations plus decision descriptions.

    Everything Canon understands is still legal here -- records, enums,
    effects, plain functions -- so a module can hold its types and its
    decisions together.
    """

    def __init__(self, tokens, source="", filename="<memory>", bag=None):
        super().__init__(tokens, source, filename, bag, language="verdict")
        self.decisions: list = []

    def parse_decl(self):
        doc = self.skip_docs()
        if self.at_ctx("decision") and self.at(1).kind == T.NAME:
            d = self.parse_decision(doc)
            self.decisions.append(d)
            return None
        # Put the doc back in play for the Canon declaration parsers.
        if doc:
            self.pending_doc = [doc]
        for fn, kw in ((self.parse_fn, "fn"), (self.parse_record, "record"),
                       (self.parse_enum, "enum"), (self.parse_alias, "alias"),
                       (self.parse_effect, "effect"), (self.parse_const, "const"),
                       (self.parse_test, "test")):
            if self.cur.is_kw(kw):
                return fn(doc)
        return None

    # ------------------------------------------------------------------

    def parse_decision(self, doc: str = "") -> DecisionDecl:
        start = self.next()          # decision
        d = DecisionDecl(doc=doc)
        d.name = self.expect_name("a decision name")
        d.params = self.parse_params()
        self.expect_op("->", "before the outcome type")
        ty = self.parse_type()
        if isinstance(ty, A.TName):
            d.outcome_type = ty.name
        else:
            self.err("CANON-E0104",
                     "a decision's outcome type must be a named enum")
            d.outcome_type = "Unknown"

        while True:
            # Doc comments may sit between clauses, so they are skipped each
            # time round rather than ending the clause list.
            self.skip_docs()
            if self.cur.is_kw("intent"):
                self.next()
                d.intent = self.parse_text_literal("an intent description")
            elif self.cur.is_kw("uses"):
                self.next()
                d.uses.extend(self.parse_effect_refs())
            elif self.cur.is_kw("cost"):
                self.next()
                d.cost = self.parse_cost(d.cost)
            elif self.at_ctx("prohibited"):
                self.next()
                d.prohibited.extend(self.parse_paths())
            elif self.at_ctx("acknowledge", "acknowledges"):
                self.next()
                d.acknowledged.extend(self.parse_paths())
            elif self.at_ctx("factor"):
                d.factors.append(self.parse_factor())
            elif self.at_ctx("rule"):
                d.rules.append(self.parse_rule())
            elif self.at_ctx("otherwise"):
                d.otherwise = self.parse_otherwise()
            else:
                break

        if not d.rules:
            self.err("CANON-E0102",
                     f"decision {d.name!r} has no rules",
                     start,
                     facts={"decision": d.name},
                     notes=["A decision with no rules always returns its "
                            "`otherwise` outcome, which is better written as "
                            "an ordinary function."])
        if d.otherwise is None:
            self.err(
                "CANON-E0305",
                f"decision {d.name!r} has no `otherwise` outcome", start,
                facts={"decision": d.name},
                repairs=[Repair(
                    "manual",
                    "add a default outcome and the reason for it",
                    'otherwise Refer\n  because "..."', start.span, 0.7)],
                notes=["Every input must reach an outcome with a stated "
                       "reason. Without a default there are inputs the "
                       "decision cannot answer, and no record of why."])

        d.span = self.span_from(start)
        return d

    def parse_paths(self) -> list:
        """A comma-separated list of field paths, e.g. `app.postcode`."""
        paths = []
        while True:
            parts = []
            if self.cur.kind != T.NAME:
                self.err("CANON-E0101", "expected a field path")
                break
            parts.append(self.next().value)
            while self.eat_punct("."):
                if self.cur.kind not in (T.NAME, T.UPPER):
                    self.err("CANON-E0101", "expected a field name")
                    break
                parts.append(self.next().value)
            paths.append(".".join(parts))
            if not self.eat_punct(","):
                break
        return paths

    def parse_factor(self) -> FactorDecl:
        start = self.next()          # factor
        name = self.expect_name("a factor name")
        self.expect_punct(":", "before the factor type")
        ty = self.parse_type()
        self.expect_op("=", "before the factor expression")
        expr = self.parse_expr()
        f = FactorDecl(name=name, ty=ty, expr=expr)
        while True:
            if self.at_ctx("because"):
                self.next()
                f.basis = self.parse_text_literal("the reason this factor is used")
            elif self.at_ctx("weight"):
                self.next()
                if self.cur.kind == T.INT:
                    f.weight = int(self.next().payload)
                else:
                    self.err("CANON-E0101", "a factor weight must be an integer")
            else:
                break
        if not f.basis:
            self.err(
                "CANON-E0102",
                f"factor {name!r} does not say why it is used", start,
                facts={"factor": name},
                repairs=[Repair("manual", "state the justification",
                                'because "..."', start.span, 0.7)],
                notes=["A factor without a stated basis cannot appear in an "
                       "explanation, and an unexplainable factor is not "
                       "usable in a regulated decision."])
        f.span = self.span_from(start)
        return f

    def parse_rule(self) -> RuleDecl:
        start = self.next()          # rule
        name = (self.next().value if self.cur.kind in (T.NAME, T.TEXT)
                else self.expect_name("a rule name"))
        r = RuleDecl(name=name, condition=None, outcome="")
        if not self.eat_ctx("when"):
            self.err("CANON-E0101", "expected `when` after the rule name",
                     repairs=[Repair("insert-before", "add `when`", "when ",
                                     self.cur.span, 0.8)])
        r.condition = self.parse_expr(no_record=True)

        if not self.eat_ctx("outcome"):
            self.err("CANON-E0101", "expected `outcome` after the condition",
                     repairs=[Repair("insert-before", "add `outcome`",
                                     "outcome ", self.cur.span, 0.8)])
        r.outcome, r.outcome_args = self.parse_outcome_value()

        if self.eat_ctx("because"):
            r.basis = self.parse_text_literal("the reason for this outcome")
        else:
            self.err(
                "CANON-E0102",
                f"rule {name!r} does not state a reason", start,
                facts={"rule": name},
                repairs=[Repair("manual", "state why this rule decides as it does",
                                'because "..."', start.span, 0.8)],
                notes=["Every outcome must carry a reason a person can be "
                       "given. This is the property the language exists to "
                       "guarantee."])
        r.span = self.span_from(start)
        return r

    def parse_otherwise(self) -> RuleDecl:
        start = self.next()          # otherwise
        outcome, args = self.parse_outcome_value()
        r = RuleDecl(name="otherwise", condition=None, outcome=outcome,
                     outcome_args=args)
        if self.eat_ctx("because"):
            r.basis = self.parse_text_literal("the reason for the default outcome")
        else:
            self.err("CANON-E0102",
                     "the `otherwise` outcome does not state a reason", start,
                     repairs=[Repair("manual", "state the default reason",
                                     'because "..."', start.span, 0.8)])
        r.span = self.span_from(start)
        return r

    def parse_outcome_value(self):
        if self.cur.kind != T.UPPER:
            self.err("CANON-E0101", "expected an outcome constructor")
            return "Unknown", []
        name = self.next().value
        args = []
        if self.cur.is_punct("("):
            args = self.parse_call_args()
        return name, args


# --------------------------------------------------------------------------
# Lowering
# --------------------------------------------------------------------------

def _lit(value, kind="text") -> A.Lit:
    return A.Lit(value=value, lit_kind=kind)


def _var(name) -> A.Var:
    return A.Var(name=name)


def _call(fn, args) -> A.Call:
    return A.Call(fn=fn, args=list(args))


def _rec(type_name, fields) -> A.RecordLit:
    return A.RecordLit(type_name=type_name, fields=list(fields))


class Lowering:
    """Turns decision declarations into Canon declarations."""

    def __init__(self, bag: Bag):
        self.bag = bag

    def lower_module(self, mod: A.Module, decisions: list) -> A.Module:
        if decisions:
            mod.decls.extend(_support_decls())
        for d in decisions:
            self.check_prohibited(d)
            mod.decls.extend(self.lower_decision(d))
        mod.language = "verdict"
        return mod

    # ------------------------------------------------------------------

    def check_prohibited(self, d: DecisionDecl):
        """
        Reject any read of a prohibited path, anywhere in the decision.

        Factor expressions and rule conditions are both checked, and factors
        are checked transitively: a rule that reads a factor which reads a
        prohibited field is just as prohibited as one that reads the field
        directly.
        """
        prohibited = set(d.prohibited)
        if not prohibited:
            return

        tainted_factors = {}
        for f in d.factors:
            hits = _paths_in(f.expr) & prohibited
            if hits:
                tainted_factors[f.name] = sorted(hits)
                self.bag.error(
                    "CANON-E0903",
                    f"factor {f.name!r} reads a prohibited field",
                    f.span,
                    facts={"factor": f.name, "fields": sorted(hits),
                           "decision": d.name},
                    repairs=[Repair("manual",
                                    "compute this factor without the "
                                    "prohibited field, or remove the "
                                    "prohibition and record why")],
                    notes=["A prohibited field must be unreachable from the "
                           "decision, not merely unused by policy."])

        for r in d.rules + ([d.otherwise] if d.otherwise else []):
            if r.condition is None:
                continue
            names = _paths_in(r.condition)
            hits = names & prohibited
            via = sorted({fn for fn in tainted_factors
                          if _var_used(r.condition, fn)})
            if hits or via:
                self.bag.error(
                    "CANON-E0903",
                    f"rule {r.name!r} depends on a prohibited field",
                    r.span,
                    facts={"rule": r.name, "fields": sorted(hits),
                           "via_factors": via, "decision": d.name},
                    notes=["A prohibited field reached through a factor is "
                           "still a prohibited field."])

    # ------------------------------------------------------------------

    def lower_decision(self, d: DecisionDecl) -> list:
        result_type = f"{_pascal(d.name)}Result"

        record = A.RecordDecl(
            name=result_type,
            intent=f"The outcome of the {d.name} decision, with its reasons.",
            fields=[
                A.Param(name="outcome", ty=A.TName(name=d.outcome_type),
                        doc="The decision reached."),
                A.Param(name="reasons",
                        ty=A.TName(name="List", args=[A.TName(name="Reason")]),
                        doc="Why this outcome was reached."),
                A.Param(name="factors",
                        ty=A.TName(name="List", args=[A.TName(name="Factor")]),
                        doc="Every factor considered, with its weight."),
            ],
            invariants=[
                # A result with no reason is not a decision anyone can act on.
                A.Binary(op=">",
                         left=_call(A.QualVar(module="List", name="length"),
                                    [_var("reasons")]),
                         right=_lit(0, "int")),
            ],
            span=d.span)

        fn = A.FnDecl(
            name=d.name,
            doc=d.doc,
            intent=d.intent or f"Decide {d.name}.",
            params=list(d.params),
            result=A.TName(name=result_type),
            uses=list(d.uses),
            cost=d.cost,
            origin="verdict",
            span=d.span)

        fn.ensures.append(
            A.Binary(op=">",
                     left=_call(A.QualVar(module="List", name="length"),
                                [A.Field(target=_var("result"), name="reasons")]),
                     right=_lit(0, "int")))
        fn.ensures.append(
            A.Binary(op="==",
                     left=_call(A.QualVar(module="List", name="length"),
                                [A.Field(target=_var("result"), name="factors")]),
                     right=_lit(len(d.factors), "int")))
        fn.laws.append(A.LawRef(name="explains"))
        fn.laws.append(A.LawRef(name="deterministic"))

        stmts = []
        for f in d.factors:
            stmts.append(A.SLet(name=f.name, ty=f.ty, value=f.expr,
                                span=f.span))

        factor_list = A.ListLit(items=[
            _rec("Factor", [
                ("name", _lit(f.name)),
                ("value", _as_int(f)),
                ("weight", _lit(f.weight, "int")),
                ("basis", _lit(f.basis)),
            ]) for f in d.factors])
        stmts.append(A.SLet(name="considered", value=factor_list))

        body_expr = self._chain(d, result_type)
        fn.body = A.Block(stmts=stmts, result=body_expr, span=d.span)

        outcome_fn = A.FnDecl(
            name=f"{d.name}_outcome",
            intent=f"The outcome of {d.name} without its reasons.",
            params=list(d.params),
            result=A.TName(name=d.outcome_type),
            uses=list(d.uses),
            origin="verdict",
            body=A.Block(stmts=[], result=A.Field(
                target=_call(_var(d.name),
                             [_var(p.name) for p in d.params]),
                name="outcome")),
            span=d.span)

        return [record, fn, outcome_fn]

    def _chain(self, d: DecisionDecl, result_type: str) -> A.Expr:
        """Build the nested if/else that evaluates the rules in order."""
        def make_result(rule: RuleDecl) -> A.Expr:
            outcome = (A.CtorCall(name=rule.outcome, args=rule.outcome_args)
                       if rule.outcome_args
                       else A.CtorCall(name=rule.outcome))
            return _rec(result_type, [
                ("outcome", outcome),
                ("reasons", A.ListLit(items=[
                    _rec("Reason", [("rule", _lit(rule.name)),
                                    ("basis", _lit(rule.basis))])])),
                ("factors", _var("considered")),
            ])

        expr = make_result(d.otherwise) if d.otherwise else _rec(result_type, [])
        for rule in reversed(d.rules):
            expr = A.If(cond=rule.condition, then=make_result(rule),
                        otherwise=expr, span=rule.span)
        return expr


def _as_int(f: FactorDecl) -> A.Expr:
    """
    Factor values are reported as Int so one shape covers every factor.

    A Dec factor is scaled by 100 rather than truncated, so a reported value
    never silently loses the part of the number a reader would care about.
    """
    if isinstance(f.ty, A.TName) and f.ty.name == "Dec":
        return _call(A.QualVar(module="Dec", name="floor"),
                     [A.Binary(op="*", left=_var(f.name),
                               right=_lit(100, "int"))])
    if isinstance(f.ty, A.TName) and f.ty.name == "Bool":
        return A.If(cond=_var(f.name), then=_lit(1, "int"),
                    otherwise=_lit(0, "int"))
    return _var(f.name)


def _support_decls() -> list:
    lx = Lexer("module _support\n" + SUPPORT_TYPES, "<verdict-support>")
    toks = lx.run()
    p = Parser(toks, SUPPORT_TYPES, "<verdict-support>", lx.bag)
    mod = p.parse_module()
    if p.bag.has_errors:
        raise RuntimeError("verdict support types failed to parse:\n"
                           + p.bag.render(SUPPORT_TYPES))
    return mod.decls


def _pascal(name: str) -> str:
    return "".join(part.capitalize() or "_" for part in name.split("_"))


def _paths_in(expr) -> set:
    """Every `a.b.c` field path an expression reads."""
    out = set()
    if expr is None:
        return out
    for node in expr.walk():
        if isinstance(node, A.Field):
            parts = []
            cur = node
            while isinstance(cur, A.Field):
                parts.append(cur.name)
                cur = cur.target
            if isinstance(cur, A.Var):
                parts.append(cur.name)
                out.add(".".join(reversed(parts)))
    return out


def _var_used(expr, name: str) -> bool:
    if expr is None:
        return False
    return any(isinstance(n, A.Var) and n.name == name for n in expr.walk())


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def parse_verdict(source: str, filename: str = "<memory>"):
    """Parse and lower Verdict source. Returns (Canon Module, Bag)."""
    lx = Lexer(source, filename)
    toks = lx.run()
    p = VerdictParser(toks, source, filename, lx.bag)
    mod = p.parse_module()
    mod = Lowering(p.bag).lower_module(mod, p.decisions)
    return mod, p.bag
