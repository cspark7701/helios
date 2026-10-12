# Execution Plans & Change Records

This directory tracks structured execution plans and repository change logs for the **HELIOS** framework, inspired by the plan-first orchestration methodology pioneered by LBNL's **Osprey**.

## Directory Structure

- `active/`: Contains currently active execution plans, ongoing development tasks, and operational proposals pending completion or review.
- `completed/`: Contains completed execution plans, milestone summaries, and repository change logs. Files in this directory are prefixed with a 5-digit sequence number (e.g., `00001_init_repo_and_plan.md`).

## Workflow

1. **Plan Formulation**: Before initiating non-trivial changes, an execution plan is drafted in `active/`.
2. **Review & Execution**: Steps are carried out according to the plan with validation and testing.
3. **Completion & Archival**: When a task or milestone is finished, the record is finalized and moved/saved into `completed/` with its 5-digit sequence identifier.
4. **Git Commit Tracking**: Every repository change is committed with formatted commit messages listing changed files and clear technical rationale.
