# Local overrides — read this BEFORE `references/upstream/`

`references/upstream/` is a byte-identical copy of the skill shipped inside
`edgartools` v5.43.0 (MIT). It is kept unmodified on purpose: rewriting the
author's text would misattribute it and destroy diffability against future
upstream releases.

The cost of that choice is that a few upstream tips are wrong or do not apply
here. **Where this file and `upstream/` disagree, this file wins.**

---

## 1. `filing.search()` results do not support slicing

`upstream/sharp-edges.yaml` (and several skill.yaml examples) show:

```python
for match in results[:5]:          # ← raises TypeError on v5.43.0
```

Measured against the pinned version: the result object accepts integer indexing
only. Slicing raises `TypeError: '>' not supported between instances of 'int'
and 'slice'`. Use:

```python
results = filing.search("China export controls")
for i in range(min(5, len(results))):
    m = results[i]
    print(m.score, str(m)[:200])
```

## 2. Identity setup does not go through `set_identity()`

Upstream tells you to call `edgar.set_identity(...)` or to export the library's
own environment variable directly. Neither is the path here:

- This agent stores the contact under its own name and resolves it from the
  environment, `~/.aisa/credentials`, and the profile `.env` — see the Setup
  section of `SKILL.md`.
- `scripts/sec_boot.py` performs that resolution and translates the value into
  whatever variable the library expects, then imports it for you.

Always start with the `boot()` preamble from `SKILL.md`. Calling
`set_identity()` yourself bypasses the resolver, so a contact the owner already
saved will look unset.

Do not relay the library's internal variable name to the owner. `SKILL.md` has
the naming rule; upstream text predates it.

## 3. Vocabulary

Upstream prose uses the SEC system name and the library name freely. In anything
the owner sees, say "SEC filings" instead. The library name is fine inside code
blocks, import statements and file paths — that is where it actually appears.

---

Everything else in `upstream/` — the API routing tables, the per-domain patterns,
the form-type mappings, the Company/Filing/Statement/XBRL reference — is accurate
for v5.43.0 and worth consulting.
