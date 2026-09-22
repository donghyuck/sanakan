---
name: sanakan-manage
description: Configure and operate Sanakan issue-driven coding automation. Use when the user asks to start, inspect, stop or retry Sanakan development and MR publication for a GitHub or GitLab project. Do not activate for unrelated coding requests.
---

# Sanakan management

Sanakan polls project issues, runs independent Codex planning/development/review sessions,
and publishes a policy-formatted Draft MR. You operate its CLI; you are not the polling loop.
Use the plugin's `scripts/manage.py` with Python 3.11+. It delegates to the bundled runtime
(or the Sanakan source checkout during plugin development). Run `--help` to verify availability.

## Before starting

Find the user's existing project configuration and run-storage path. Never invent a hosting project,
reviewer ID, baseline, approval expiration or credentials. Reuse an already authorized setup.
For a new setup, inspect the local clone and its AGENTS/CONTRIBUTING/commit/MR templates,
then prepare the project configuration. Required authorization covers the target project,
automatically eligible issues, allowed paths, verification commands and publication formats.
Use `examples/runner/automation-project.json` in the tool checkout as a source example;
a packaged plugin also includes it under `assets/automation-project.json`.
For GitHub.com, use assets/github-project.json and assets/GITHUB.md in the package.
Keep Draft and reviewer-request/readback rules identical to GitLab; do not convert a rejected Draft automatically.
The example expiration and commit are placeholders that must be replaced.

Automatic services require execution.backend=docker, a preinstalled digest-pinned image, and
SANAKAN_HANDOFF_DIR / SANAKAN_HANDOFF_KEY_FILE on both trusted hosts. The key file must be private
(chmod 600); never mount it in executors. Use distinct private run stores for develop and publish.
Local run results are development-only and cannot be exported/published.
Read the packaged assets/EXECUTION_BOUNDARY.md for setup and migration from 1.4.

Check `status` before starting a second process. Development and publication are separate roles:
- `start --role develop`: requires SANAKAN_READ_TOKEN and Codex authentication; reject a publish token.
- `start --role publish`: requires SANAKAN_PUBLISH_TOKEN in the separate trusted publisher environment.
Do not start both roles with a shared credential environment or copy credentials into files or prompts.
Do not create a Codex heartbeat in addition to the Sanakan watcher; that would duplicate scheduling.
A request to inspect status alone does not authorize starting a watcher or publishing changes.

## Commands

Use the absolute plugin script path in these examples, and the user's actual settings/storage paths:

```sh
python3 <plugin>/scripts/manage.py status --config <project.json> --runs <run-storage>
python3 <plugin>/scripts/manage.py start --role develop --config <project.json> --runs <run-storage>
python3 <plugin>/scripts/manage.py start --role publish --config <project.json> --runs <run-storage>
python3 <plugin>/scripts/manage.py stop --role all --config <project.json> --runs <run-storage>
python3 <plugin>/scripts/manage.py retry --iid <number> --config <project.json> --runs <run-storage>
```

The stop command is cooperative: no new phase is admitted after stop is observed, but the current
subprocess may run until it exits or times out. Confirm `running: false` before claiming it stopped.
`retry` requeues failed development in a new generation and preserves old artifacts. Publication
retry reuses the verified patch and queries existing branch/MR state; never force push or clear
state to bypass an error. Retry only the requested issue after examining the recorded reason.
For needs_revalidation, stop both watchers and confirm they have stopped, then run retry --mode revalidate on the development store to create a fresh generation.
Do not keep retrying the old publication or revalidate on the publisher.
Published jobs are not reimplemented by retry. Changed policies or issue revisions need fresh validation.

## Report

Report actual service running/stopped state, job phase, failure/questions and MR URL when present.
A local `ready` job is not a published MR. A mock test is not a live Codex/GitLab success.
Do not claim the plugin is an MCP server or that installation alone starts background work.
