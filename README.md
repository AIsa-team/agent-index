# AIsa Agent Index

This repository is the public distribution surface for AIsa AgentSpec agents.

It is consumed by the AIsa CLI, the Claude Code and Codex plugin marketplaces,
and runtime automation. Nothing here is agent source — this repo carries the
index, the marketplace, and the built artifacts.

## What Is In Here

| Surface | Contents | Consumers |
|---|---|---|
| Index | `index.json` (`agent-index/v1`) | AIsa CLI, backend sandbox provisioning, E2B entrypoint, in-agent version self-check |
| Marketplace | `.claude-plugin/marketplace.json`, `marketplace.json`, `plugins/` | Claude Code, Codex |
| Releases | GitHub Releases tagged `<id>-v<version>` | Direct downloads, install scripts, AI-guided installs |

`index.json` is the service discovery entry point — consumers read it and use
only the URLs it provides, rather than assembling release URLs themselves:

```text
https://raw.githubusercontent.com/AIsa-team/agent-index/main/index.json
```

The raw endpoint is CDN-cached and can lag a few minutes behind a fresh
publish.

## Installing An Agent

Replace `aisa-cio` with the agent id you want. Ids and the current `latest`
version are listed in `index.json`.

**Claude Code plugin**

```bash
claude plugin marketplace add AIsa-team/agent-index
```

```bash
claude plugin install aisa-cio@aisa-agents
```

Updates ship through the marketplace: `claude plugin marketplace update aisa-agents`.

**Codex plugin**

```bash
codex plugin marketplace add AIsa-team/agent-index
```

Then open the **Plugins** directory in the ChatGPT desktop app, pick the
`aisa-agents` marketplace, and install the agent — Codex has no
`plugin install` CLI command. Updates: `codex plugin marketplace upgrade`.

**Hermes profile / OpenClaw agent**

Use the AIsa CLI (`aisa agent install` / `aisa agent update`), which resolves
everything through the index and verifies the SHA-256 checksum. For a manual
install, each release carries a per-target `INSTALL-<target>.md` and
`install-<target>.sh`.

Every install form seeds the same user data directory
(`~/.aisa/agents/<id>/`) and never overwrites your own files.

## Published Targets

Each published version carries four build targets:

| Target | Form | Artifact |
|---|---|---|
| `hermes` | url | Hermes profile bundle (`<id>-hermes-v<version>.tar.gz`) |
| `openclaw` | url | Pre-seeded OpenClaw isolated agent workspace |
| `claude-plugin` | git | `plugins/<id>/` at a pinned tag + commit |
| `codex-plugin` | git | `plugins/<id>-codex/` at a pinned tag + commit |

`plugins/` always mirrors the most recent release; earlier versions are
reachable through their `<id>-v<version>` tags, which is what the git-form
index entries pin.

## Index Shape

```jsonc
{
  "spec": "agent-index/v1",
  "agents": {
    "<id>": {
      "name": "...", "description": "...",
      "repo": "AIsa-team/agent-index",
      "latest": "<version>",              // only ever points at a complete release
      "versions": {
        "<version>": { "targets": { "<target>": { /* see below */ } } }
      }
    }
  }
}
```

Two target shapes:

- **url form** (`hermes`, `openclaw`) — `url` + `sha256`, plus `installMd`,
  `installSh`, `guidePrompt`. An `e2bTemplate` field appears only when a
  versioned E2B fast-boot template has been baked successfully and matches that
  version; it applies to `hermes` only.
- **git form** (`claude-plugin`, `codex-plugin`) — `repo` + `tag` + `commit` +
  `path`, plus `installMd`. Immutability comes from git rather than a checksum,
  because neither host's marketplace accepts archive URLs as a plugin source.

Consumers must check the top-level `spec`. The schema evolves only by adding
optional fields; the meaning of a published field never changes.

Each agent retains its five highest versions in the index; older entries are
trimmed on publish, and `latest` is always retained. Trimming an entry from the
index does not delete its GitHub Release.

## Do Not Edit This Repository By Hand

`README.md` is the only hand-maintained file. Everything else — `index.json`,
both marketplace manifests, and all of `plugins/` — is generated and pushed by
the internal release tooling.

Manual edits break more than they fix. Publishing updates `index.json` through
the GitHub contents API as a read-modify-write with conflict replay, so a
hand-authored commit can be silently overwritten or leave the index disagreeing
with the releases it points at — which breaks installs, updates, checksum
verification, and sandbox provisioning.

If a version, artifact URL, checksum, or release entry needs to change, change
it in the authoritative AgentSpec source project and publish it through the
release tooling.
