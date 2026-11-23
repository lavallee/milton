# Fleet collection and the dashboard

Milton can report across several machines without merging their evidence
into one store. Each host keeps its own coverage declaration, and the fleet
view shows host projections next to their sum.

```console
milton fleet collect --hosts hosts.toml --out ~/.local/share/milton/fleet
milton serve --fleet ~/.local/share/milton/fleet --bind 127.0.0.1 --port 8917
```

## How collection works

For each host in the manifest, `milton fleet collect`:

1. Runs `milton scan` **on that host** over SSH (or locally for
   `ssh = "local"`). The scan uses the default metadata content policy:
   transcript, tool, and message bodies are hashed and redacted there, and
   raw bodies never leave the host. The collector has no option to change this.
2. Runs from a per-command state directory on the host
   (`state_dir/<hash of the milton command>`). Changing the Milton command or
   version therefore builds a fresh store, as [the changelog's normalization
   note](../CHANGELOG.md) requires, rather than mixing normalizer versions.
3. Copies back only that normalized store (`rsync`), then computes a snapshot
   with the collector's own projections: the report, accounting, and the
   cost-per-outcome summary for the window.
4. Writes `OUT/<host>/events.db`, `OUT/<host>/snapshot.json`, and an
   `OUT/index.json` that records each host's status (`ok`, `partial`,
   `error`, or `unreachable`), the error tail, and `last_success_at`.

A host whose scan or copy fails keeps its previous store and snapshot, so the
dashboard shows the last good projection next to the current failure. A
`partial` status means `milton scan` exited 1 because at least one adapter
failed. The adapter's coverage row says which one.

Hosts are scanned in parallel (`--workers`, default 4). `--host NAME`
collects a subset and leaves the other entries in the index untouched.

## The hosts manifest

```toml
[collect]
since = "30d"                          # scan and projection window
milton = "milton"                      # command run on each host
state_dir = "~/.local/state/milton/fleet"
timeout_seconds = 1800
sources = []                           # extra ADAPTER=PATH roots for every host
adapters = []                          # empty = all built-in adapters

[[hosts]]
name = "workstation"
ssh = "local"                          # run here, without SSH

[[hosts]]
name = "build-box"
ssh = "build-box.example"              # any ssh destination or config alias
sources = ["git=~/src"]                # appended to [collect].sources
```

`milton` can be any command that runs a compatible Milton, for example
`uvx --from milton-ai==0.2.0 milton` or a Git revision through
`uvx --from git+https://github.com/lavallee/milton@REV milton`. Pin it to the
collector's version: the collector reads the copied store with its own schema
and fails closed on a mismatch.

The scan runs from the state directory, not from the SSH session's home.
This matters because the memory-file adapters default to the working directory
and Git defaults to its parent. To include them, name their roots in
`sources`.

Remote hosts need SSH key access in batch mode, `rsync`, and the Milton
command on `PATH`. The scan prepends `~/.local/bin`, `/opt/homebrew/bin`, and
`/usr/local/bin`. The collector needs `ssh` and `rsync`.

## The dashboard

`milton serve` is a read-only, standard-library HTTP server over the
collection directory. It never opens an event store; it renders the snapshot
files, so pages are cheap and show exactly the projections on disk.

| Path | Content |
| --- | --- |
| `/` | Hosts, collection status, events, selected cost, source coverage |
| `/hosts/NAME` | Per-adapter events, cost, tokens, gaps; ingestion coverage; cost per outcome |
| `/api/fleet.json` | The fleet summary document |
| `/api/hosts/NAME/snapshot.json` | One host's snapshot |
| `/health` | `{"status": "ok", "collected_at": ...}` |

`--findings PATH` adds a count of current findings by grade from a findings
ledger.

The server has no authentication. Bind it to loopback or to a private network
interface, and put any access control in front of it.

Fleet totals add host projections. They do not deduplicate a cost observation
recorded on more than one host, such as a shared gateway ledger synced to two
machines. If that applies to your fleet, scan the shared source on one host
only.
