# Development and Git workflow

This repository uses feature branches and pull requests. `main` is the reviewed, runnable delivery branch. A development checkpoint is not a release or proof that every roadmap feature is complete.

The current delivery scope and user-controlled checkpoints are recorded in [the knowledge release plan](docs/releases/knowledge-v0.2.md). The [PRD](docs/PRD-research-knowledge.md) retains the longer-term roadmap. When a checkpoint finishes, report the result and wait for the user's explicit decision before starting the next one. Elapsed time, automatic continuations and an unanswered question are not approval.

## Branches and commits

- Use `codex/<feature-or-fix>` for agent-created development branches. This release uses `codex/research-knowledge-v1`, based on `main` at `a1d417ef4d0d6822d813f0e70e5c6bb00ef3a41e`.
- Create the feature branch before committing existing working-tree changes. Keep unrelated user changes intact. Do not reset, rewrite or clean the working tree to prepare a commit.
- Prefer cohesive commits such as `feat(knowledge): ...`, `fix(graph): ...`, `test(evaluation): ...` and `docs: ...`. A truthful checkpoint commit may preserve an already interdependent implementation; do not manufacture a historical series of independently passing commits.
- Inspect the staged diff and file list before each commit. Check whitespace and unintended generated files. Record actual verification and remaining limitations.
- Push the feature branch for backup. Do not commit directly to `main`, force-push shared history or create a release tag for an unaccepted checkpoint.

## Pull requests and merge

1. Keep changes on the feature branch through the approved implementation checkpoints. A Draft PR may be used if the user requests early review; the current four-checkpoint plan creates the delivery PR in checkpoint 4.
2. Describe the concrete user behavior, scope, schema/configuration changes, actual verification and known limitations. Separate implemented, tested and deferred work. Use the repository PR template.
3. Check the latest `main` and resolve conflicts on the feature branch. Rerun affected checks after conflict resolution or material fixes. Never report an earlier check as verification of a changed head.
4. Before merge, inspect the final diff, check results and open review findings. Missing checks are not passing checks; fix blocking failures or report them to the user. Do not change repository protections or bypass required checks to merge.
5. Merge through a PR into `main` only after the relevant checkpoint is explicitly authorized and its acceptance gates pass. This delivery has user authorization for PR/merge in checkpoint 4, conditional on authorization to start that checkpoint and successful checks.
6. Verify the remote merge commit and local tracking state. Create a version tag only when the delivered scope is accepted; choose the next version from existing tags. Do not delete the feature branch unless asked.
7. After this release is merged and verified, pause work. Deferred features require the user's next instruction.

## Verification and evidence

- Run checks appropriate to the changed behavior. The current app uses TypeScript strict checking, Next.js production builds, Python domain tests and real-service integration tests. Runtime persistence is PostgreSQL, not a SQLite substitute.
- Database changes require explicit Alembic migrations and compatibility/recovery checks. Background jobs need cancellation, retry/redelivery and partial-result coverage where relevant.
- Model and financial quality claims require actual runs and attributable evidence. Synthetic tests, HTTP 200 responses, Langfuse traces and successful builds do not establish answer accuracy.
- Follow [app UI requirements](copilotkit-app/AGENTS.md): after a changed build starts, refresh the actual page and check affected and adjacent flows, both languages and themes, loading/empty/error states, scrolling and navigation. Mobile checks are currently deferred by the user; say so in delivery notes.
- Record test commands, results, dates/configurations and unverified paths in [validation records](docs/validation/research-knowledge-validation.md). Do not claim unfinished modules passed.
- Continuous integration is a checkpoint-4 deliverable. Until actual workflows/check results exist, document local checks as local checks; do not advertise CI enforcement.

## Credentials, data and generated output

- Stage only source, configuration templates, dependency locks, migrations, tests and appropriate documentation. `.env.example` values must remain placeholders.
- Never commit real `.env` files, API/OAuth credentials, private keys, databases, dumps, logs, caches, `.next`, dependency directories or local research artifacts. Do not print secret values in verification output.
- `local-data/` and private service configuration remain ignored. Original PDFs, rendered pages and extracted corpora stay outside Git unless redistribution rights have been checked and inclusion is explicitly intended. Public download access alone does not grant redistribution rights.
- Check the staged content before pushing, including newly added files that are absent from ordinary `git diff --stat`. Confirm remote branch/commit after pushing.
- A GitHub push publishes repository changes according to the repository's existing visibility; it does not authorize changing visibility, deploying a public service or exposing local ports.

## Useful local commands

```powershell
git status --short
git diff --cached --stat
git diff --cached --check

# In copilotkit-app, when application checks are required:
npx tsc --noEmit
npm run build

# In copilotkit-app/agent, with isolated test services configured:
uv run python -m unittest discover -s tests -v
```

Stop only the verified project frontend before a Windows standalone build if it holds generated output files open; restart and check the built page afterward. Do not stop unrelated processes. Source-only checkpointing or documentation changes do not imply a deployment or justify repeated full model runs.
