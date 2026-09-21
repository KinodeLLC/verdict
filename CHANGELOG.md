# Changelog

Keep a Changelog format, SemVer. Pre-1.0: breaking changes bump the minor.

## [Unreleased]

## [0.1.0] - 2026-09-21

### Added
- Decisions with factors, weighted rules and a required default outcome.
- Mandatory reasons: a rule, a factor or a default without a stated basis does
  not compile.
- Prohibited factors enforced by reachability, including through factors, with
  the route named in the diagnostic.
- Lowering to a result record carrying outcome, reasons and every factor
  considered, with contracts and the `explains` law attached.
