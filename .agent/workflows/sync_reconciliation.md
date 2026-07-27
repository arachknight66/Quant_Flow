---
name: sync_reconciliation
description: Orchestrates the Knowcode sync and reconciliation loop.
trigger: /know-sync
---

# Sync Reconciliation Workflow

When the user invokes `/know-sync`, you must execute the complete reconciliation loop. Do not skip any steps.

### Execution Sequence:
1. **Structural Sync:** Run the terminal command `know sync`. Wait for it to complete.
2. **Buffer Check:** Check if `.agent/memory/previous_context.md` exists. 
   - *Note: If this file does not exist, it means there were no structural changes. Stop the workflow here and inform the user.*
3. **Synthesis:** Load the skill `.agent/skills/synthesize_knowledge.md` and execute its instructions to synthesize the sync state.
4. **Semantic Commit:** Once synthesis is written to disk, run the terminal command `know sync-semantic`. This will bump the semantic revision and the CLI will delete the previous context buffer.
5. **Completion:** Summarize the architectural updates you just made to the user.