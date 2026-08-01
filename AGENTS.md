# AGENTS.md

## Purpose

This repository is being developed using a requirements-first approach.

The authoritative project requirements are stored in the `requirements/` directory.

Agents must treat those files as the source of truth.

Do not duplicate requirements in code comments, design documents, or this file unless there is a strong reason to do so.

---

## Requirements Process

Before implementing a feature:

1. Read all relevant requirement files.
2. Check for conflicts.
3. Check for missing requirements.
4. If requirements conflict:
   - Stop implementation.
   - Request clarification.

Do not silently resolve requirement conflicts.

Do not invent requirements.

If implementation reveals a missing requirement:

1. Stop.
2. Document the requirement/issue in approriate requirement file.
3. Request clarification.

Requirements are more important than implementation.

---

## Working Style

The project owner is an experienced software architect and engineer.

Assume:

- strong software engineering knowledge
- strong systems design knowledge
- strong C++ knowledge
- strong Python knowledge
- strong TypeScript and JavaScript knowledge
- experience designing modern web interfaces

When the user asks to add a new feature, start by confirming requirements first. Don't capture major requirement and implementation in a single pass. The project owner will review the requirement interpretation before implementation should start.

---

## Implementation Guidance

Always:

- Mark the implemented requirement as "Implemented" once implemented.

Prefer:

- simple solutions
- straightforward pipeline and script-based approaches
- maintainable designs
- explicit code

Avoid:

- unnecessary abstraction
- unnecessary framework extensions
- unnecessary dependencies
- overly clever designs

---

## Security Guidance

Security requirements are first-class requirements.

Never weaken security requirements for convenience.

When implementing authentication, authorisation, auditing, permissions, or identity integration:

- explain the security model
- explain trust boundaries
- explain risks
- explain common mistakes

Security-sensitive code should prioritise clarity over cleverness.

---

## Code Generation Guidance

Prefer:

- small changes
- focused commits
- incremental delivery

When generating code:

- explain the intent
- explain non-obvious framework behaviour
- associate every new unit test with the requirement ID it verifies with a simple comment.

Assume maintainability is more important than speed of implementation.

---

## Verification Guidance

Prefer the repository scripts in `scripts/` for development verification so agents and developers run checks in a consistent way.

Common commands:

- `python3 scripts/typecheck-python.py`
- `python3 scripts/check-all.py`

Use focused test arguments when appropriate instead of running the full suite unnecessarily.

---

## Questions and Uncertainty

When uncertain:

- state assumptions clearly
- identify risks
- identify alternatives
- ask the user to do an experiment or debug something

Do not present guesses as facts.

It is acceptable to stop and request clarification when requirements are unclear.
