# AGENTS.md

## Purpose

This repository is being developed using a requirements-first approach.

The authoritative project requirements are stored in the `requirements/` directory.

Agents must treat those files as the source of truth.

Do not duplicate requirements in code comments, design documents, or this file unless there is a strong reason to do so.

---

## Confidential Sample Data — Hard Rule

`sample-data/confidential/` may contain company-confidential documents used for local development and testing. Agents may inspect and process these files locally when necessary for a user-requested test, diagnosis, or verification.

Treat all contents, filenames, paths below that directory, and metadata from that directory as confidential. Do not upload, send to external services, copy, quote, summarise, or disclose them outside the local testing context.

No confidential content, identifier, metadata, or document-specific detail from these files may be copied into or represented in a committed artifact: code, tests, fixtures, requirements, features, documentation, examples, prompts, logs, issue descriptions, or commit messages. Tests and fixtures committed to the repository must use synthetic data only. Agents may make general, content-independent changes informed by a locally observed compatibility defect, but must not encode the confidential input or its distinctive characteristics.

Local evaluation artifacts derived from confidential samples may be written only below the gitignored `outputs/evaluations/` subtree. They may be used only for local inspection. Do not upload, send, stage, commit, quote, summarise, log, or otherwise disclose those artifacts or their contents. Do not add, stage, or commit files from `sample-data/confidential/` or other derived /confidential/ folders. The developer is ultimately responsible for reviewing local test activity and all changes before committing.

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
