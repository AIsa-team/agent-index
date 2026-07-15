# AIsa Agent Index

This repository is the public distribution index for AIsa AgentSpec agents.

It is consumed by the AIsa CLI and runtime automation as the central registry of
published agent versions and downloadable runtime artifacts. The primary file is
`index.json`, which follows the `agent-index/v1` schema and points consumers to
versioned release assets such as Hermes profile bundles.

## What This Project Means

This is not an agent source repository and it is not the place to edit agent
behavior.

In the AgentSpec release flow, agent source projects are built and published by
the internal producer tooling. Publishing creates release artifacts, computes
checksums, and updates this repository's `index.json`. Consumers then read:

```text
https://raw.githubusercontent.com/AIsa-team/agent-index/main/index.json
```

to discover the latest available agent versions and install or update them.

## Do Not Edit Generated Content Manually

Do not manually change the contents of this project.

Everything in this repository, except this `README.md`, is generated and
published automatically. Manual edits to generated files or release artifacts
can break installs, updates, checksum verification, and runtime deployment.

If an agent version, artifact URL, checksum, or release entry needs to change,
make the change in the authoritative AgentSpec source project and publish it
through the release tooling instead of editing this repository by hand.
