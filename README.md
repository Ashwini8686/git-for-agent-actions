# Git for Agent Actions

**A transaction-safety layer for AI agents that make changes to real
user data.**

Git for Agent Actions is an MCP-oriented project designed to make
agent-driven actions reviewable, controlled, and auditable.

**Target workflow:** Stage → Diff → Approve → Commit → Verify → Revert\*

\*Revert is possible only when a supported compensation action exists.
Some actions, such as sending an email, cannot be reliably undone.

## The problem

AI agents can call tools that modify files and other user data. When
multiple actions happen in sequence, users need a clear way to
understand what will change, approve consequential actions, detect
conflicts, and inspect the outcome.

Without a transaction-control layer, users may face: - Changes happening
before they can review the full plan. - Limited visibility into what an
agent intends to modify. - Conflicts when data changes between planning
and execution. - Unclear recovery when only part of a multi-step
operation succeeds.

## Our approach

Git for Agent Actions is designed to put a control layer between an AI
agent and write-capable tools.

1.  **Stage** --- collect proposed operations without immediately
    applying their changes.
2.  **Diff** --- present intended changes for inspection.
3.  **Approve** --- require human authorization before controlled
    execution.
4.  **Commit** --- execute approved operations through controlled
    adapters.
5.  **Verify** --- check the resulting state and record the outcome.
6.  **Revert** --- run a supported compensation action when one exists;
    this is not guaranteed for irreversible operations.

## Current implementation status

The following status reflects the implementation milestones completed so
far.

### Implemented

-   Sandboxed filesystem adapter with path-confinement and traversal
    protections.
-   Filesystem inspection operations, including file information,
    directory listing, existence checks, text reading, and SHA-256
    hashing.
-   Controlled filesystem mutation methods.
-   Domain-specific exceptions and pytest fixtures.
-   SQLAlchemy data model with 13 tables.
-   SQLite configuration with foreign-key enforcement and WAL mode.
-   Transaction state machine with 12 states, legal-transition
    validation, timestamps, and audit logging.

### Next build stages

-   Staging manager and idempotency handling.
-   Diff generation.
-   Human approval flow.
-   Controlled execution, verification, and supported compensation
    handling.
-   MCP server integration and user-facing interface.

### Roadmap

-   Additional tool adapters, such as calendar and email integrations.
-   A dashboard for reviewing and managing agent transactions.
-   Team and organization-oriented controls.

**Note:** Items under "Next build stages" and "Roadmap" are planned
work, not claims that those features are already complete.

## Design principles

-   **Preview before mutation:** staging and review should happen before
    controlled writes.
-   **Explicit authorization:** consequential operations should require
    approval.
-   **Least privilege:** agents should access write operations only
    through the controlled gateway.
-   **Conflict awareness:** re-check relevant preconditions before
    execution.
-   **Auditable execution:** record state transitions and operation
    outcomes.
-   **Honest recovery guarantees:** compensation is best-effort and
    depends on the action; irreversible side effects must not be
    described as undoable.

## Technology

-   Python
-   SQLAlchemy
-   SQLite
-   Sandboxed filesystem adapter
-   pytest

The project is being developed with an MCP-native integration approach.
Additional integrations and interface components are planned.

## Repository status

This is an actively developed hackathon project. The current codebase
contains foundational filesystem-sandboxing and
transaction-persistence/state-management components. The complete Stage
→ Diff → Approve → Commit → Verify → Revert workflow is the target
architecture and is being implemented incrementally.

## Getting started

Setup and run instructions will be added once the repository's
dependency manifest and application entry point are finalized.

## Team

-   **Team:** Winhack
-   **Event:** wHACKiest 2026
-   **Track:** Make MCP Matter --- Less Magic, More Utility

## License

No license has been specified yet. All rights are reserved by default
unless a license is added to this repository.
