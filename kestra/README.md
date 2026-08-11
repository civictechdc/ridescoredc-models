# kestra/ — the pipeline definition

**This folder is authoritative for the data pipeline.** What runs, in what
order, on what schedule, against which database — it is all here, in version
control, reviewed like code.

What is *not* here: the scoring logic. Flows clone this repository and run the
`ridescore` CLI from [`tools/ridescore-cli/`](../tools/ridescore-cli/) — the
same command a modeler runs in a notebook. There is deliberately no
`kestra/scripts/`; a second copy of the model is a second model.

---

## The server

| | |
|---|---|
| UI + API | **https://pipeline-ridescore.mocomakers.com** |
| Tenant | `main` — the prefix in every API path, `/api/v1/main/...` |
| Repo it syncs | `github.com/civictechdc/ridescoredc-models`, branch `main` |

**That URL is expected to change.** It appears in this table and nowhere else —
not in any flow. Flows never need to know their own hostname, so a rename is a
one-line diff here plus the GitHub webhook target.

### Logging in, and the API

Kestra OSS has **one shared administrator account**. The web UI login, `curl`,
and any agent or script all use the *same* email and password over HTTP Basic
Auth. There is no separate API key and no per-person account — that needs
Kestra Enterprise. Treat the login as full control of the pipeline, and note
that it is not the same thing as the webhook key.

```bash
curl -s -u 'you@example.com:password' \
  'https://pipeline-ridescore.mocomakers.com/api/v1/main/flows/prod.ridescore/build_scores'
```

---

## Namespaces

Folders map to namespaces automatically, via `includeChildNamespaces` on the
sync flow:

| Folder | Namespace | Holds |
|--------|-----------|-------|
| `flows/sync/` | `prod.sync` | the git sync itself |
| `flows/ridescore/` | `prod.ridescore` | fetch, build, load, diagnostics |
| `flows/example/` | `prod.example` | the loop-works smoke flow |
| — | `dev.*` | safe experiments, created by hand in the UI |

Child namespaces inherit secrets from their parent, so a secret set on `prod`
is readable from `prod.ridescore`.

`legacy/` sits **outside** `flows/`, so sync never reads it. Park a flow there
rather than deleting it when its YAML no longer validates — one broken file
under `flows/` is one failed import on every sync.

---

## The flows

| Flow | Phase | Does |
|------|-------|------|
| `prod.sync.sync_git_flows` | — | pulls `kestra/flows/` from `main` into Kestra |
| `prod.ridescore.volume_mount_test` | diagnostic | **run this first** — proves the host mount persists |
| `prod.ridescore.fetch_sources` | A | Open Data DC → dated snapshot in Tier 2 |
| `prod.ridescore.build_scores` | B | snapshot → scored artifacts |
| `prod.ridescore.load_database` | C | artifacts → rows in `ridescoredc` |
| `prod.ridescore.refresh_all` | all | A→B→C as subflows, with a disabled schedule |

Split into phases because **build is the part you re-run.** A weight change
should be judged against yesterday's snapshot, not against a fresh download
that moved underneath you.

---

## Where data lives — three tiers

```
Tier 1  execution scratch    WorkingDirectory, /tmp/kestra-wd/…/{executionId}/
        lifetime: ONE EXECUTION.  for: the git clone, temp files.

Tier 2  host cache           /var/lib/kestra/ridescore/{raw,out}
        in containers:       /data/raw, /data/out
        lifetime: until wiped.    for: dated snapshots, built artifacts.

Tier 3  the warehouse        ridescoredc, crashes_dc
        lifetime: until the next load.  for: what the website serves.
```

**The rule:** never write a snapshot into the working directory. It is Tier 1
and is reclaimed the moment the execution ends — so `raw/<date>/` would vanish
before anything could ever be compared against it, which defeats the entire
reason the cache is dated.

### The three-layer mount

A Tier 2 path has to be declared in **three** places. Mounting it on the Kestra
service alone does nothing, because script tasks run in *sibling* containers
spawned through `docker.sock` — they do not inherit the Kestra container's
mounts.

1. **compose**, on the `kestra` service:
   `- /var/lib/kestra/ridescore:/data:rw`
2. **compose**, inside `KESTRA_CONFIGURATION`, so the runner may mount at all:
   `volume-enabled: true` under
   `kestra.plugins.configurations` for
   `io.kestra.plugin.scripts.runner.docker.Docker`
3. **every script task**, in its own `taskRunner.volumes:`

Create the host directory once:

```bash
sudo mkdir -p /var/lib/kestra/ridescore/{raw,out}
```

Then run `volume_mount_test` with `mode=write`, and again with `mode=read`.
Two separate executions — the second is what proves the data outlived the
first. Skipping this and going straight to `fetch_sources` means debugging a
mount problem through an hour-long download.

---

## Deploying a change

Two loops. Know which one you are in.

**A — git first.** Edit a file here, open a PR into `develop`, merge to `main`.
The webhook fires `sync_git_flows` and the live flow updates. This is the
default and the only one that leaves a reviewable record.

**B — API first,** for fast iteration:

| | |
|---|---|
| update a flow | `PUT /api/v1/main/flows/{namespace}/{id}` with `Content-Type: application/x-yaml` |
| execute | `POST /api/v1/main/executions/{namespace}/{id}`, inputs as `-F key=value` |
| poll | `GET /api/v1/main/executions/{id}` |
| logs | `GET /api/v1/main/logs/{id}` |

```bash
curl -u 'USER:PASS' -X POST \
  'https://pipeline-ridescore.mocomakers.com/api/v1/main/executions/prod.ridescore/build_scores' \
  -F area=Petworth -F git_branch=main
```

**The conflict rule: whichever lands last wins.** An API edit that is not
mirrored back into this folder and pushed to `main` is **reverted** by the next
sync. The `PUT` response contains a `source` field with canonical YAML — paste
it back into `kestra/flows/` and commit.

### Webhook

```
https://pipeline-ridescore.mocomakers.com/api/v1/main/executions/webhook/prod.sync/sync_git_flows/{WEBHOOK_KEY}
```

This authenticates on the **path key only**, not the UI login. The key is a
password sitting in a URL: rotate it if it lands in a log or a screenshot.

### Staging

The repository follows Gitflow — `develop` is staging, `main` is production. To
mirror that in Kestra, add a second sync flow with `branch: develop` and
`targetNamespace: dev`, and point a second webhook at it. Keep it out of
`flows/sync/`, or the prod sync will import it and the two will fight.

---

## Secrets

Never inline. In a flow: `{{ secret('PG_HOST') }}`. The names are listed in
[`secrets.example.env`](secrets.example.env); the values live only on the
server.

```bash
cd ~/Projects/kestra-ridescore
# Encode KEY=value lines only. A '#' comment breaks Docker's env_file parsing.
grep -v '^#' .env | grep -v '^$' | grep '=' | while IFS='=' read -r k v; do
  echo "SECRET_${k}=$(printf '%s' "$v" | base64 -w0)"
done > .env_encoded

sudo docker compose down && sudo docker compose up -d
```

---

## Plugin property names

Kestra's git plugin renamed several properties, and most examples online are
older than the rename. If a flow fails with `Unrecognized field`, check here:

| Deprecated | Current |
|------------|---------|
| `uri:` | `url:` |
| `cloneDirectory:` on Clone | `directory:` |
| `directory:` on TenantSync | `gitDirectory:` |
| `io.kestra.core.models.triggers.types.Webhook` | `io.kestra.plugin.core.trigger.Webhook` |

We use `SyncFlows`, not `TenantSync` — it matches this folder layout as is.
`TenantSync` expects `kestra/{namespace}/flows/{id}.yaml`, which would mean
restructuring the tree for no gain.

---

## When something fails

```bash
# state, and the status of each task
curl -s -u USER:PASS \
  'https://pipeline-ridescore.mocomakers.com/api/v1/main/executions/{id}' \
  | jq '.state.current, (.taskRunList[] | {task: .taskId, state: .state.current})'

# logs
curl -s -u USER:PASS \
  'https://pipeline-ridescore.mocomakers.com/api/v1/main/logs/{id}' | jq -r '.[].message'
```

| Symptom | Cause | Fix |
|---------|-------|-----|
| `can't cd to repo` | clone and script in different containers | wrap both in `WorkingDirectory` |
| script cannot see `/data/raw` | one of the three mount layers missing | run `volume_mount_test` |
| snapshot gone next run | written to Tier 1, not Tier 2 | check `cache_path` is `/data/raw` |
| `Cannot find secret for key` | missing `.env_encoded` entry | add, re-encode, restart compose |
| `Unrecognized field "uri"` | old plugin syntax | see the table above |
| sync imports a broken flow | bad YAML under `flows/` | move it to `legacy/`; `ignoreInvalidFlows` limits the blast radius |
| Kestra won't start | bad indentation in `KESTRA_CONFIGURATION` | `docker compose logs kestra` |

---

## First-time bring-up

1. Stand up the compose stack (Postgres for metadata + Kestra), with
   `basic-auth` set in `KESTRA_CONFIGURATION` rather than the Setup page —
   config wins over the database, so restarts stay predictable.
2. `sudo mkdir -p /var/lib/kestra/ridescore/{raw,out}` and add the three mount
   layers above.
3. Add secrets, encode, restart.
4. Create `sync_git_flows` by hand — through the UI or a `PUT`. It is the only
   flow you ever deploy manually; it deploys the rest.
5. Point a GitHub webhook at the URL above and push to `main`.
6. Run `hello_world` — proves the sync loop works.
7. Run `volume_mount_test`, write then read — proves Tier 2 persists.
8. Only then run `fetch_sources`.
