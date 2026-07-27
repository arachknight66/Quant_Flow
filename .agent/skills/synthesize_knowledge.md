---
name: synthesize_knowledge
description: Skill to reconcile staged intent or legacy documents and update the permanent knowledge base.
---

# Knowledge Synthesis & Classification

When called upon to synthesize knowledge, you are acting as the Chief Architect. You must classify information and deposit it into the correct buckets.

### Step 1: Branching Execution
**If invoked by `/know-sync`:**
1. Read `.agent/memory/previous_context.md` (The Intent/Why).
2. Read the latest `.knowcode/reports/R-XXX.md` report (The Reality/What).
3. Reconcile: Compare the intent against reality. Did the structural changes match the intent? If there is a contradiction, the structural report is the absolute truth.

**If invoked by `/know-ingest`:**
1. Read the raw documents located in `.knowcode/knowledge/raw/`. 
2. Do NOT cross-reference structural reports. Simply extract the architectural knowledge from the legacy files.

### Step 2: Knowledge Distribution
Take the validated insights and append them to the appropriate Markdown files within `.knowcode/knowledge/`:

- `architecture/architecture.md`: High-level system design, data flow, subsystem responsibilities, and boundaries.
- `decisions/decisions.md`: Architecture Decision Records (ADRs). The choice made, alternatives considered, and the trade-off rationale.
- `constraints/constraints.md`: System invariants, import firewalls, security boundaries, and strict rules that must not be broken.
- `conventions/conventions.md`: Styling, naming patterns, file structure, and formatting rules.
- `components/components.md`: Specific component behaviors, public API contracts, and state machines.

### Formatting Rules:
- Append to existing files. Do not overwrite.
- Use clear markdown `##` headings for new topics.
- Keep descriptions precise and factual.