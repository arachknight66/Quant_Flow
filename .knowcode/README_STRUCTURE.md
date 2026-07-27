# KnowCode Instance: Quant_Flow

This directory (`.agent/`) is the active governance and behavior root for this repository. It defines how autonomous agents should interact with, maintain, and evolve the codebase.

## The Dual-Folder Architecture

* **`.agent/` (Behavior & Governance):** You are here. This directory contains instructions, workflows, and skills that dictate *how* the AI operates.
* **`.knowcode/` (Passive Knowledge & State):** The sibling directory. It contains deterministic AST snapshots, reports, logs, and persistent semantic state. `.knowcode/` has no operational governance.

## Subsystems

* **Runtime:** Orchestrates operations and manages this artifact structure.
* **Structural Engine:** Owns `state.yaml` and parses the repository into deterministic snapshots.

## Directory Structure
- `skills/`: Markdown definitions of agent capabilities and functions.
- `workflows/`: Orchestration sequences defining how agents tackle complex, multi-step goals.

**Note:** The state lockfile (`.knowcode/state.yaml`) is managed exclusively by the Structural Engine. Do not edit it manually.