---
description: Add an architecture decision record to docs/DECISIONS.md
---

Create a new ADR titled: $ARGUMENTS

1. Open `docs/DECISIONS.md` and find the next number (see the comment at the bottom).
2. Append an entry in the existing format:
   - `## ADR-NNN: <title>`
   - **Status:** Proposed (use Accepted only after the user agrees). Include today's date and who chose it (the user or Claude).
   - **Context:** the problem and constraints, 2 to 4 sentences.
   - **Decision:** one clear sentence, then specifics if needed.
   - **Consequences:** what gets easier, what gets harder, what to revisit and when.
3. If it supersedes an earlier ADR, mark the old one `Superseded by ADR-NNN` (the only allowed edit to an old ADR).
4. Update the "Next number" comment at the bottom of the file.
5. Add a one-line summary under **Decisions** in `MEMORY.md`.
6. If the decision changes the design, update `docs/ARCHITECTURE.md` in the same change.
7. If the decision is Proposed and needs the user's call, ask the user a single, specific question.
