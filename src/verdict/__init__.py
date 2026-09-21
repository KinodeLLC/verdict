"""
Verdict: a decision language for regulated logic.

A decision compiles only if it can explain itself: every rule states a reason,
every decision has a default, and prohibited factors are unreachable rather
than merely unused. Verdict lowers to Canon, so the verifier, the capability
analysis, the journal and the promotion gate all apply to it unchanged.
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
