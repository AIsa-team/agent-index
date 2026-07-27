"""Resolve the SEC identity, then hand back a ready-to-use edgar module.

Why this exists: `edgartools` reads EDGAR_IDENTITY from os.environ ONLY. But on a
plugin install the agent guides the owner to write credentials into
~/.aisa/credentials, which never reaches the process environment. Without this
resolver the documented setup flow dead-ends: the owner does exactly what the
skill told them to, and the next call still raises IdentityNotSetException.

Resolution order mirrors skills/_shared/aisa_client.py:
    env var  ->  ~/.aisa/credentials  ->  hermes profile .env files

Usage (from the skill's venv python):
    import sys; sys.path.insert(0, "<skill>/scripts")
    from sec_boot import boot
    edgar = boot()                       # exits with guidance if unconfigured
    print(edgar.Company("NVDA").name)

Persisting an identity the owner just supplied in chat:
    python sec_boot.py --set "Jane Doe jane@example.com"

--set exists so the agent never has to hand-roll the write. Doing it by shell
would mean getting .env quoting right (the value contains spaces and .env is
shell-sourced, so an unquoted line breaks profile rendering), picking the right
target file per install form, and not appending duplicates.

The value is NOT validated. The SEC asks callers to declare a contact but does
not check the header, so what to declare is the owner's decision; this script
stores and forwards whatever they give it.
"""

import os
import shlex
import sys

_KEY = "SEC_IDENTITY"          # the name this skill asks the owner for
_LIB_KEY = "EDGAR_IDENTITY"    # what edgartools reads from os.environ; also the
                               # name this skill used before v1.1.0 (legacy reads)
_READ_KEYS = (_KEY, _LIB_KEY)

_CREDENTIAL_FILES = (
    "~/.aisa/credentials",                     # plugin installs (no hermes profile)
    "~/.hermes/.env",
    "~/.hermes/profiles/manager/.env",
)

_UNSET_MESSAGE = (
    "SEC identity is not set.\n"
    "The SEC requires every automated filing request to declare a real contact, and\n"
    "rejects undeclared automated access outright (HTTP 403).\n"
    "\n"
    "This is NOT an API key - there is nothing to sign up for. It is the owner's own\n"
    "name and email, e.g. 'Jane Doe jane@example.com'.\n"
    "\n"
    "Do NOT make the owner edit a file, and do NOT search the disk for a saved\n"
    "credential. Ask them in the conversation, then save it for them:\n"
    "\n"
    "    {script} --set \"Their Name their@email.com\"\n"
    "\n"
    "That writes to the right place for this install (profile .env, correctly\n"
    "quoted, or ~/.aisa/credentials) and takes effect on the next call.\n"
    "\n"
    "Ask the owner what to declare -- it is their call. Do not pick a value for\n"
    "them without asking.\n"
    "\n"
    "This is NOT a signal to go find another data source. Do not quietly switch to\n"
    "marketpulse or web search and answer as though nothing happened: neither\n"
    "serves filing section text, and asked for one they may answer from a different,\n"
    "older filing. Ask the owner first. If they decline or are unreachable, say\n"
    "plainly that the answer is not from the filing and name what you used instead."
)


def resolve_identity():
    """Return the configured SEC identity, or "" if none is available.

    The current name is searched across EVERY source before the legacy name is
    tried anywhere. Source-first ordering would let a stale legacy value left in
    the process environment outrank the identity the owner just saved.
    """
    for key in _READ_KEYS:
        found = _resolve_key(key)
        if found:
            return found
    return ""


def _resolve_key(key):
    """env var -> this profile's .env -> shared credential files, for one name."""
    value = os.environ.get(key)
    if value and value.strip():
        return value.strip()

    # THIS profile's .env comes first and must be searched: set_identity() writes
    # there on hermes/openclaw installs. Reading a different set of paths than we
    # write would mean --set appears to succeed and the very next call still says
    # "not configured" -- observed in an end-to-end run, where the agent worked
    # around it by exporting the variable by hand.
    prefix = key + "="
    own_env = _hermes_profile_env()
    search = ([own_env] if own_env else []) + list(_CREDENTIAL_FILES)
    for path in search:
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            continue
        try:
            with open(path) as handle:
                for line in handle:
                    line = line.strip()
                    if line.startswith(prefix):
                        found = _unquote(line[len(prefix):])
                        if found:
                            return found
        except OSError:
            continue          # unreadable credential file is not fatal; keep looking
    return ""


def _unquote(raw):
    """Undo shell quoting on a KEY=VALUE right-hand side.

    Must handle what we write (`shlex.quote`, which emits single-quoted words and
    renders an embedded ' as '"'"'), what a human may have typed by hand
    (double-quoted, or bare), and the credentials file (always bare). Naive
    .strip('"').strip("'") mangles the shlex.quote form and would silently return
    a truncated identity.
    """
    raw = raw.strip()
    if not raw:
        return ""
    try:
        parts = shlex.split(raw, comments=True)
    except ValueError:
        # unbalanced quotes -- fall back to the literal text rather than dropping it
        return raw.strip('"').strip("'")
    return " ".join(parts).strip() if parts else ""


def _hermes_profile_env():
    """Nearest ancestor that looks like an installed profile, else None.

    A hermes/openclaw profile is the directory holding agent.json above the
    skills tree. Plugin installs also carry agent.json-adjacent layouts but have
    no .env -- those fall through to ~/.aisa/credentials.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        here = os.path.dirname(here)
        if not here or here == "/":
            break
        if os.path.exists(os.path.join(here, "agent.json")) and \
           os.path.exists(os.path.join(here, ".env")):
            return os.path.join(here, ".env")
    return None


def _upsert(path, line, key_prefix):
    """Replace an existing KEY= line or append; never leave duplicates."""
    existing = []
    if os.path.exists(path):
        with open(path) as handle:
            existing = handle.read().splitlines()
    out, replaced = [], False
    for row in existing:
        if row.strip().startswith(key_prefix):
            if not replaced:
                out.append(line)
                replaced = True
            continue                      # drop any further duplicates
        out.append(row)
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.append(line)
    with open(path, "w") as handle:
        handle.write("\n".join(out) + "\n")
    os.chmod(path, 0o600)


def _strip_key(path, key_prefix):
    """Drop every line for a superseded key name. No-op when there is none.

    Without this, --set leaves the pre-rename line in the file. On hermes and
    openclaw the profile .env is shell-sourced, so that stale line still reaches
    os.environ, where it could outrank the value just saved.
    """
    if not os.path.exists(path):
        return
    with open(path) as handle:
        rows = handle.read().splitlines()
    kept = [r for r in rows if not r.strip().startswith(key_prefix)]
    if len(kept) == len(rows):
        return
    with open(path, "w") as handle:
        handle.write("\n".join(kept) + ("\n" if kept else ""))
    os.chmod(path, 0o600)


def set_identity(value):
    """Persist the identity where THIS install reads it. Returns the path.

    The value is passed through verbatim: whatever the owner supplies is what
    goes on the wire. The SEC asks callers to declare a contact but does not
    validate the header, so this is the owner's call to make, not ours.
    """
    value = (value or "").strip()
    if not value:
        raise ValueError("value is empty")
    # Both destinations are line-oriented: a newline would let one value inject a
    # second KEY=VALUE line. Control characters have no place in a contact string.
    if any(c in value for c in "\r\n\x00"):
        raise ValueError("value must be a single line (no newlines or NUL)")

    env_path = _hermes_profile_env()
    if env_path:
        # .env is shell-sourced and the value contains spaces -> must be quoted,
        # or profile rendering aborts with 'Doe: command not found'.
        # shlex.quote produces a SINGLE-quoted shell word, so nothing inside it is
        # expanded when the profile sources .env. Double-quoting with only `"`
        # escaped is not enough: `Jane $(cmd) x@y.com` and backticks still execute,
        # which turns an owner-supplied (or prompt-injected) identity into RCE.
        _upsert(env_path, "{}={}".format(_KEY, shlex.quote(value)), _KEY + "=")
        _strip_key(env_path, _LIB_KEY + "=")
        return env_path

    cred = os.path.expanduser("~/.aisa/credentials")
    os.makedirs(os.path.dirname(cred), exist_ok=True)
    # credentials is parsed as KEY=VALUE (split on the first "="), not sourced,
    # so the value is stored raw -- quotes here would become part of the value.
    _upsert(cred, "{}={}".format(_KEY, value), _KEY + "=")
    _strip_key(cred, _LIB_KEY + "=")
    return cred


def boot():
    """Ensure the identity is in the environment, then import and return `edgar`.

    Exits with actionable guidance rather than letting edgartools raise a bare
    IdentityNotSetException, which tells the owner nothing about how to fix it.
    """
    identity = resolve_identity()
    if not identity:
        # Render the real interpreter + script path so the fix is copy-pasteable
        # rather than a template the agent has to reconstruct.
        sys.exit(_UNSET_MESSAGE.format(
            script="{} {}".format(sys.executable, os.path.abspath(__file__))))
    # edgartools reads ONLY its own variable name (edgar/core.py sets
    # edgar_identity = 'EDGAR_IDENTITY'; edgar/httprequests.py reads it per
    # request). Translate here, and never surface that name to the owner.
    os.environ[_LIB_KEY] = identity

    import edgar
    return edgar


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--set":
        if len(sys.argv) != 3:
            sys.exit('usage: sec_boot.py --set "Name email@domain.com"')
        try:
            written = set_identity(sys.argv[2])
        except ValueError as exc:
            sys.exit("Not saved: {}.".format(exc))
        # Confirm the destination, not the value - it is the owner's personal contact.
        print("SEC identity saved to {}".format(written))
        print("Takes effect on the next call; no restart needed.")
        sys.exit(0)

    # Diagnostic: report configuration state without making a network call.
    found = resolve_identity()
    if found:
        # Do not echo the full value - it is the owner's personal email.
        print("SEC identity: configured ({} chars)".format(len(found)))
    else:
        # Print the SAME actionable guidance as boot(). A bare "NOT configured"
        # reads as a dead end, and an agent that hits a dead end routes around it
        # -- observed in testing: it silently fell back to another data source and
        # answered from the PRIOR year's 10-K while calling it the latest.
        print("SEC identity: NOT configured\n", file=sys.stderr)
        print(_UNSET_MESSAGE.format(
            script="{} {}".format(sys.executable, os.path.abspath(__file__))),
            file=sys.stderr)
        sys.exit(1)
