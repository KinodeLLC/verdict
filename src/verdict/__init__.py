"""
verdict, a decision language for regulated logic.

a decision only compiles if it can explain itself. every rule states a reason,
every decision has a default, and prohibited factors are unreachable rather
than just unused. it lowers to canon so the verifier and the capability
analysis and the journal and the gate all work on it already.
"""

__version__ = "0.1.0"

from .lang import (  # noqa: E402
    LANGUAGE_VERSION,
    DecisionDecl,
    FactorDecl,
    Lowering,
    RuleDecl,
    VerdictParser,
    parse_verdict,
)

__all__ = [
    "__version__", "LANGUAGE_VERSION",
    "parse_verdict", "VerdictParser", "Lowering",
    "DecisionDecl", "FactorDecl", "RuleDecl",
]
