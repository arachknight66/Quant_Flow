# Raw Knowledge Inbox

This directory (`.knowcode/knowledge/raw/`) is the inbox for legacy or unstructured documentation.

## Workflow

1. **Drop files here:** Drop your old PDFs, markdown files, or text documents into this folder.
2. **Agent Synthesis:** Ask the Semantic Agent to read the files and distribute the knowledge into the proper architectural documents (e.g., `architecture.md`, `decisions.md`).
3. **Commit & Cleanup:** Once the agent is done extracting information from a file, it will run `know ingest-semantic <filename>` to delete the file and safely bump the knowledge base revision. Alternatively, the agent can run `know ingest-semantic .` to wipe the entire inbox at once.