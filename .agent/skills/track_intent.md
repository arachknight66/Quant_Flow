---
name: track_intent
description: The passive skill for distilling developer intent into the active context buffer.
---

# Intent Tracking (The Prime Directive)

This is a passive background skill. While you are pair-programming, writing code, and answering questions, you must continuously distill the *Why* behind the development session.

### Rules for Tracking:
1. **Listen for Intent:** Identify design decisions, architectural shifts, new constraints discovered, and the reasoning behind code changes.
2. **Append Silently:** Write these insights as 1-2 sentence bullet points into `.agent/memory/active_context.md`. Do this silently in the background without asking the user for permission.
3. **No Code:** Do NOT log raw code snippets. The physical code is tracked by Git. You are tracking the *Why*.
4. **Append-Only:** Never overwrite or truncate `active_context.md`. Only append. Never flush this file manually.