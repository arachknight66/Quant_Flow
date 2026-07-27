---
name: ingest_legacy
description: Orchestrates the processing and cleanup of legacy knowledge documents.
trigger: /know-ingest
---

# Legacy Ingestion Workflow

When the user invokes `/know-ingest`, you must process the raw inbox.

### Execution Sequence:
1. **Inbox Check:** List the files in `.knowcode/knowledge/raw/`. If it is empty (or only contains `README.md`), stop the workflow and inform the user.
2. **Synthesis:** Load the skill `.agent/skills/synthesize_knowledge.md` and execute its instructions to process the raw documents.
3. **Semantic Commit & Cleanup:** Once synthesis is written to disk, run the terminal command `know ingest-semantic .`. This will bump the semantic revision and the CLI will delete all the raw files.
4. **Completion:** Summarize the knowledge you extracted and which buckets you updated.