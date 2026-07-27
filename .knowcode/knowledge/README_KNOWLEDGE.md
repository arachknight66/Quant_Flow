# Knowledge Maintenance Protocol

This directory contains the human-facing architectural guidelines, constraints, conventions, and component documentation for the repository.

## Organization
- `architecture/`: High-level system design, sub-system descriptions, and boundaries.
- `decisions/`: ADRs (Architecture Decision Records) explaining *why* a particular path was chosen.
- `constraints/`: System invariants and "Trap" documentation. These are rules that must not be broken.
- `conventions/`: Style, formatting, and language-specific rules.
- `components/`: Specific component contracts and behaviors.

This structure allows AI agents to orient themselves, understand system boundaries, and avoid regressions by reading explicitly defined constraints.