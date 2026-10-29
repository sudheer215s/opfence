# Writes catalog/heroku/data-*.yaml and their fixtures: the Heroku Data API
# (api.data.heroku.com) as the Heroku CLI calls it.
# Run from the repo root: python3 -I herokudatagen.py
import json, os, re

CLI = "https://github.com/heroku/cli/blob/main/src/"
UTIL = "https://github.com/heroku/heroku-cli-util/blob/main/src/"
UNLISTED = "Heroku Data API on api.data.heroku.com, which no published schema describes; read from the Heroku CLI"
D = "catalog/heroku/"
APP = "shop-api"
DB = "6f1c2a7e-3b9d-4e5f-8a1b-2c3d4e5f6a7b"
DBNAME = "postgresql-shaped-48213"
REDIS = "redis-curved-77120"

R = []  # rules


def rule(group, verb, method, path, cls, src, card=None, res="db", when=None, notes=None, tests=None, body=None, query=None, fpath=None):
    R.append(dict(group=group, verb=verb, method=method, path=path, cls=cls, src=src if isinstance(src, list) else [src],
                  card=card, res=res, when=when or [], notes=notes, tests=tests, body=body, query=query, fpath=fpath))


C11 = "/client/v11/databases/{add_on_id_or_name}"
TR = "/client/v11/apps/{app_id_or_name}/transfers"
V0 = "/postgres/v0/databases/{add_on_id_or_name}"
ADV = "/data/postgres/v1/{add_on_id_or_name}"
MNT = "/data/maintenances/v1"
RD = "/redis/v0/databases/{add_on_id_or_name}"
TRANSFER_URLS = ("Transfers carry from_url and to_url: the backup's storage URL and, for pg:copy, the database URLs "
                 "with their passwords. Reading secrets is credential.")

# Classic Postgres: backups and copies (transfers).
rule("postgres", "list-transfers", "GET", TR, "credential", CLI + "commands/pg/backups/index.ts",
     card="List Postgres backups and copies of app {app_id_or_name}", res="app", notes=TRANSFER_URLS)
rule("postgres", "read-transfer", "GET", TR + "/{transfer}", "credential", [CLI + "commands/pg/backups/info.ts", CLI + "lib/pg/backups.ts"],
     card="Read Postgres backup or copy {transfer} of app {app_id_or_name}", res="app", notes=TRANSFER_URLS,
     tests=[("call", None, None, "credential"), ("verbose", None, "verbose=true", "credential")])
rule("postgres", "delete-transfer", "DELETE", TR + "/{transfer}", "irreversible", CLI + "commands/pg/backups/delete.ts",
     card="Delete Postgres backup {transfer} of app {app_id_or_name}", res="app",
     notes="A deleted backup cannot be recovered.")
rule("postgres", "cancel-transfer", "POST", TR + "/{transfer}/actions/cancel", "write", CLI + "commands/pg/backups/cancel.ts",
     card="Cancel Postgres backup or copy {transfer} of app {app_id_or_name}", res="app")
rule("postgres", "transfer-public-url", "POST", TR + "/{transfer}/actions/public-url", "credential",
     [CLI + "commands/pg/backups/url.ts", CLI + "commands/pg/backups/download.ts"],
     card="Create a download link for Postgres backup {transfer} of app {app_id_or_name}", res="app",
     notes="Returns a signed URL that lets anyone download the backup, the whole database, for a while.")

# Classic Postgres: databases.
rule("postgres", "read", "GET", C11, "credential", [CLI + "commands/pg/info.ts", CLI + "lib/pg/types.ts"],
     card="Read Postgres database {add_on_id_or_name}, with its password",
     notes="The response includes database_password and resource_url, the connection URL with the password, "
           "so pg:info and the commands that look a database up read its password.")
rule("postgres", "capture-backup", "POST", C11 + "/backups", "write", CLI + "commands/pg/backups/capture.ts",
     card="Capture a backup of Postgres database {add_on_id_or_name}")
rule("postgres", "read-bastion", "GET", C11 + "/bastion", "credential", UTIL + "utils/pg/bastion.ts",
     card="Read the bastion host and SSH key of Postgres database {add_on_id_or_name}",
     notes="Returns the private key of the bastion that reaches a database in a Private Space.")
rule("postgres", "burst-status", "GET", C11 + "/burst_status", "read", CLI + "commands/pg/diagnose.ts")
rule("postgres", "metrics", "GET", C11 + "/metrics", "read", CLI + "commands/pg/diagnose.ts")
rule("postgres", "attach-connection-pooling", "POST", C11 + "/connection-pooling", "credential",
     CLI + "commands/pg/connection-pooling/attach.ts",
     card="Attach a connection pooler for Postgres database {add_on_id_or_name} to app {body.app}",
     body={"app": APP, "credential": "default", "name": "DATABASE_CONNECTION_POOL"},
     notes="Like attaching an add-on, it gives the app a config var with the pooler's URL and password.")
rule("postgres", "kill-connections", "POST", C11 + "/connection_reset", "write", CLI + "commands/pg/killall.ts",
     card="End every connection to Postgres database {add_on_id_or_name}",
     notes="Terminates every connection for every credential; open transactions roll back.")
rule("postgres", "list-links", "GET", C11 + "/links", "read", CLI + "commands/pg/links/index.ts")
rule("postgres", "create-link", "POST", C11 + "/links", "access", CLI + "commands/pg/links/create.ts",
     card="Link Postgres database {add_on_id_or_name} to {body.target}", body={"target": REDIS, "as": "cache"},
     notes="Gives the database a foreign-data link, with credentials, to another Heroku Postgres or Redis database, "
           "so whoever can query this one can read the other.")
rule("postgres", "delete-link", "DELETE", C11 + "/links/{link}", "delete", CLI + "commands/pg/links/destroy.ts",
     card="Remove link {link} from Postgres database {add_on_id_or_name}")
rule("postgres", "reset", "PUT", C11 + "/reset", "irreversible", CLI + "commands/pg/reset.ts",
     card="Reset Postgres database {add_on_id_or_name}, deleting all its data",
     notes="pg:reset drops every table and all data in the database.")
rule("postgres", "restore", "POST", C11 + "/restores", "irreversible", CLI + "commands/pg/backups/restore.ts",
     card="Restore a backup into Postgres database {add_on_id_or_name}, replacing its data",
     body={"backup_url": "https://xfrtu.s3.amazonaws.com/b005/backup.dump", "extensions": []},
     notes="Replaces everything in the target database with the backup's contents.")
rule("postgres", "stats-reset", "PUT", C11 + "/stats_reset", "write", CLI + "commands/pg/stats-reset.ts",
     card="Reset the statistics of Postgres database {add_on_id_or_name}",
     notes="Calls pg_stat_reset(): usage statistics start again from zero; no data changes.")
rule("postgres", "list-backup-schedules", "GET", C11 + "/transfer-schedules", "read", CLI + "commands/pg/backups/schedules.ts")
rule("postgres", "schedule-backups", "POST", C11 + "/transfer-schedules", "write", CLI + "commands/pg/backups/schedule.ts",
     card="Schedule daily backups of Postgres database {add_on_id_or_name}",
     body={"hour": "02", "timezone": "UTC", "schedule_name": "DATABASE_URL"})
rule("postgres", "unschedule-backups", "DELETE", C11 + "/transfer-schedules/{schedule}", "irreversible",
     CLI + "commands/pg/backups/unschedule.ts",
     card="Stop scheduled backups {schedule} of Postgres database {add_on_id_or_name}",
     notes="Scheduled backups are the copy a later mistake is recovered from: turning off a safety net is as "
           "dangerous as what it protects.")
rule("postgres", "copy", "POST", C11 + "/transfers", "irreversible", CLI + "commands/pg/copy.ts",
     card="Copy {body.from_name} over {body.to_name}, replacing its data",
     body={"from_name": "database shop on db.example.com:5432", "from_url": "postgres://db.example.com/shop",
           "to_name": "HEROKU_POSTGRESQL_RED", "to_url": "postgres://ec2.compute.amazonaws.com/d1"},
     notes="pg:copy overwrites the target database with the source; the URLs carry passwords, so the card names "
           "the databases instead.")
rule("postgres", "unfollow", "PUT", C11 + "/unfollow", "write", CLI + "commands/pg/unfollow.ts",
     card="Stop follower {add_on_id_or_name} following its leader",
     notes="The follower becomes a writable database; its data stays.")
for v, f in [("cancel", "cancel"), ("dry_run", "dryrun"), ("prepare", "prepare"), ("run", "run")]:
    rule("postgres", "upgrade-" + v.replace("_", "-"), "POST", C11 + "/upgrade/" + v, "write", CLI + f"commands/pg/upgrade/{f}.ts",
         card="Postgres upgrade " + v.replace("_", " ") + " for {add_on_id_or_name}",
         notes="Major version upgrades keep the data, as RDS engine upgrades do." if v == "run" else None)
rule("postgres", "upgrade-status", "GET", C11 + "/upgrade/wait_status", "read", CLI + "commands/pg/upgrade/wait.ts")
rule("postgres", "wait-status", "GET", C11 + "/wait_status", "read", CLI + "commands/pg/wait.ts")

# Classic Postgres: settings and credentials (/postgres/v0).
rule("postgres", "read-config", "GET", V0 + "/config", "read", CLI + "commands/pg/settings/index.ts")
rule("postgres", "update-config", "PATCH", V0 + "/config", "write", CLI + "lib/pg/setter.ts",
     card="Change settings of Postgres database {add_on_id_or_name}", body={"log_min_duration_statement": 2000})
rule("postgres", "list-credentials", "GET", V0 + "/credentials", "credential", [CLI + "commands/pg/credentials.ts", CLI + "lib/data/types.ts"],
     card="List the credentials of Postgres database {add_on_id_or_name}, with passwords",
     notes="Each credential comes with its users and their passwords.")
rule("postgres", "create-credential", "POST", V0 + "/credentials", "access", CLI + "commands/pg/credentials/create.ts",
     card="Create credential {body.name} on Postgres database {add_on_id_or_name}", body={"name": "analytics"},
     notes="A new database role that can log in.")
rule("postgres", "read-credential", "GET", V0 + "/credentials/{credential}", "credential", CLI + "commands/pg/credentials/url.ts",
     card="Read credential {credential} of Postgres database {add_on_id_or_name}, with its password")
rule("postgres", "delete-credential", "DELETE", V0 + "/credentials/{credential}", "access", CLI + "commands/pg/credentials/destroy.ts",
     card="Destroy credential {credential} of Postgres database {add_on_id_or_name}",
     notes="Removes a database role and every login it had.")
rule("postgres", "rotate-credential", "POST", V0 + "/credentials/{credential}/credentials_rotation", "credential",
     CLI + "commands/pg/credentials/rotate.ts",
     card="Rotate the password of credential {credential} of Postgres database {add_on_id_or_name}", body={"forced": False},
     notes="Sets a new password, a secret-store value; with forced, open connections end.")
rule("postgres", "rotate-credentials", "POST", V0 + "/credentials_rotation", "credential", CLI + "commands/pg/credentials/rotate.ts",
     card="Rotate the passwords of every credential of Postgres database {add_on_id_or_name}", body={"forced": False, "all": True},
     notes="Sets new passwords, secret-store values; with forced, open connections end.")
rule("postgres", "repair-default-credential", "POST", V0 + "/repair-default", "access", CLI + "commands/pg/credentials/repair-default.ts",
     card="Repair the default credential's permissions on Postgres database {add_on_id_or_name}",
     notes="Changes which objects the default role owns and can reach.")

# Postgres Advanced (/data/postgres/v1).
rule("postgres-advanced", "levels", "GET", "/data/postgres/v1/levels/advanced", "read", CLI + "commands/data/pg/levels.ts", res=None)
rule("postgres-advanced", "pricing", "GET", "/data/postgres/v1/pricing", "read", CLI + "lib/data/utils.ts", res=None)
rule("postgres-advanced", "list-credentials", "GET", ADV + "/credentials", "credential",
     [CLI + "commands/data/pg/credentials/index.ts", CLI + "lib/data/types.ts"],
     card="List the credentials of Postgres database {add_on_id_or_name}, with passwords",
     notes="Each credential comes with its roles and their passwords.")
rule("postgres-advanced", "create-credential", "POST", ADV + "/credentials", "access", CLI + "commands/data/pg/credentials/create.ts",
     card="Create credential {body.name} on Postgres database {add_on_id_or_name}", body={"name": "analytics"},
     notes="A new database role that can log in.")
rule("postgres-advanced", "read-credential", "GET", ADV + "/credentials/{credential}", "credential", CLI + "commands/data/pg/credentials/url.ts",
     card="Read credential {credential} of Postgres database {add_on_id_or_name}, with its password")
rule("postgres-advanced", "delete-credential", "DELETE", ADV + "/credentials/{credential}", "access",
     CLI + "commands/data/pg/credentials/destroy.ts",
     card="Destroy credential {credential} of Postgres database {add_on_id_or_name}",
     notes="Removes a database role and every login it had.")
rule("postgres-advanced", "rotate-credential", "POST", ADV + "/credentials/{credential}/rotate", "credential",
     CLI + "commands/data/pg/credentials/rotate.ts",
     card="Rotate the password of credential {credential} of Postgres database {add_on_id_or_name}", body={"force": False},
     notes="Sets a new password, a secret-store value.")
rule("postgres-advanced", "rotate-credentials", "POST", ADV + "/rotate_credentials", "credential",
     CLI + "commands/data/pg/credentials/rotate.ts",
     card="Rotate the passwords of every credential of Postgres database {add_on_id_or_name}", body={"force": False},
     notes="Sets new passwords, secret-store values.")
rule("postgres-advanced", "info", "GET", ADV + "/info", "read", [CLI + "commands/data/pg/info.ts", CLI + "lib/data/types.ts"],
     notes="Plan, pools, hosts and status; no passwords.")
PUB = ADV + "/logical-replication/publications"
rule("postgres-advanced", "list-publications", "GET", PUB, "read", CLI + "commands/data/pg/logical-replication/publications/index.ts")
rule("postgres-advanced", "create-publication", "POST", PUB, "write", CLI + "commands/data/pg/logical-replication/publications/create.ts",
     card="Create logical replication publication {body.name} on {add_on_id_or_name}", body={"name": "orders", "tables": ["public.orders"]})
rule("postgres-advanced", "read-publication", "GET", PUB + "/{publication}", "read", CLI + "commands/data/pg/logical-replication/publications/info.ts")
rule("postgres-advanced", "update-publication", "PUT", PUB + "/{publication}", "write",
     CLI + "commands/data/pg/logical-replication/publications/update.ts",
     card="Change logical replication publication {publication} on {add_on_id_or_name}", body={"tables": ["public.orders", "public.items"]})
rule("postgres-advanced", "delete-publication", "DELETE", PUB + "/{publication}", "delete",
     CLI + "commands/data/pg/logical-replication/publications/destroy.ts",
     card="Delete logical replication publication {publication} on {add_on_id_or_name}",
     notes="Subscribers stop receiving changes; the tables are untouched.")
rule("postgres-advanced", "enable-publishing", "POST", ADV + "/logical-replication/publishing/enable", "access",
     CLI + "commands/data/pg/logical-replication/publishing/enable.ts",
     card="Let subscribers replicate data from Postgres database {add_on_id_or_name}",
     notes="Turns on logical replication publishing, a way for subscribers outside Heroku to copy published tables.")
rule("postgres-advanced", "enable-subscribing", "POST", ADV + "/logical-replication/subscribing/enable", "write",
     CLI + "commands/data/pg/logical-replication/subscribing/enable.ts",
     card="Let Postgres database {add_on_id_or_name} subscribe to logical replication")
rule("postgres-advanced", "list-migrations", "GET", ADV + "/migrations", "read", CLI + "commands/data/pg/migrate.ts")
rule("postgres-advanced", "create-migration", "POST", ADV + "/migrations", "write", CLI + "commands/data/pg/migrate.ts",
     card="Set up a migration from {body.source_id} into Postgres database {add_on_id_or_name}",
     body={"method": "logical", "source_id": "0b1c2d3e-4f50-6172-8394-a5b6c7d8e9f0"})
rule("postgres-advanced", "run-migration", "POST", ADV + "/migrations/run", "irreversible", CLI + "commands/data/pg/migrate.ts",
     card="Start the migration into Postgres database {add_on_id_or_name}",
     notes="data:pg:migrate copies a classic database into an existing Advanced one, replacing what the target holds.")
rule("postgres-advanced", "cancel-migration", "POST", ADV + "/migrations/cancel", "write", CLI + "commands/data/pg/migrate.ts",
     card="Cancel the migration into Postgres database {add_on_id_or_name}")
rule("postgres-advanced", "create-pool", "POST", ADV + "/pools", "money", CLI + "lib/data/create-pool.ts",
     card="Add pool {body.name} ({body.count} x {body.level}) to Postgres database {add_on_id_or_name}",
     body={"name": "readers", "count": 2, "level": "4G-Performance"},
     notes="Adds billed compute instances.")
rule("postgres-advanced", "update-pool", "PATCH", ADV + "/pools/{pool}", "money", CLI + "commands/data/pg/update.ts",
     card="Change pool {pool} of Postgres database {add_on_id_or_name}", body={"count": 4},
     notes="Can add instances or move them to a larger, billed level.")
rule("postgres-advanced", "delete-pool", "DELETE", ADV + "/pools/{pool}", "delete", CLI + "commands/data/pg/update.ts",
     card="Remove pool {pool} from Postgres database {add_on_id_or_name}",
     notes="Removes compute instances; the data stays with the database.")
rule("postgres-advanced", "list-quotas", "GET", ADV + "/quotas", "read", CLI + "commands/data/pg/quotas/index.ts")
rule("postgres-advanced", "read-quota", "GET", ADV + "/quotas/{quota_type}", "read", CLI + "commands/data/pg/quotas/index.ts")
rule("postgres-advanced", "update-quota", "PATCH", ADV + "/quotas/{quota_type}", "write", CLI + "commands/data/pg/quotas/update.ts",
     card="Change the {quota_type} quota of Postgres database {add_on_id_or_name}",
     body={"warning_threshold": 12, "critical_threshold": 15, "enforcement_action": "notify"})
rule("postgres-advanced", "read-settings", "GET", ADV + "/settings", "read", CLI + "commands/data/pg/settings.ts")
rule("postgres-advanced", "update-settings", "PUT", ADV + "/settings", "write", CLI + "commands/data/pg/settings.ts",
     card="Change settings of Postgres database {add_on_id_or_name}", body={"settings": {"log_lock_waits": "on"}})
rule("postgres-advanced", "upgrade", "POST", ADV + "/upgrade/run", "write", CLI + "commands/data/pg/upgrade/run.ts",
     card="Upgrade Postgres database {add_on_id_or_name} to version {body.version}", body={"version": "17"},
     notes="Major version upgrades keep the data, as RDS engine upgrades do.")
rule("postgres-advanced", "wait-status", "GET", ADV + "/wait_status", "read", CLI + "commands/data/pg/wait.ts")

# Maintenance.
rule("maintenance", "list-for-app", "GET", MNT + "/apps/{app_id_or_name}", "read", CLI + "commands/data/maintenances/index.ts", res="app")
rule("maintenance", "read", "GET", MNT + "/{add_on_id_or_name}", "read", CLI + "commands/data/maintenances/info.ts")
rule("maintenance", "history", "GET", MNT + "/{add_on_id_or_name}/history", "read", CLI + "commands/data/maintenances/history.ts",
     tests=[("call", None, "limit=10", "read")], fpath=MNT + "/{add_on_id_or_name}/history/")
rule("maintenance", "run", "POST", MNT + "/{add_on_id_or_name}/run", "write", CLI + "commands/data/maintenances/run.ts",
     card="Run maintenance on {add_on_id_or_name} now",
     notes="Restarts or fails over the database now instead of in its window.")
rule("maintenance", "schedule", "POST", MNT + "/{add_on_id_or_name}/schedule", "write", CLI + "commands/data/maintenances/schedule.ts",
     card="Schedule maintenance on {add_on_id_or_name}", body={"weeks": 2})
rule("maintenance", "read-window", "GET", MNT + "/{add_on_id_or_name}/window", "read", CLI + "commands/data/maintenances/window/index.ts")
rule("maintenance", "update-window", "POST", MNT + "/{add_on_id_or_name}/window", "write",
     CLI + "commands/data/maintenances/window/update.ts",
     card="Move the maintenance window of {add_on_id_or_name} to {body.window}", body={"window": "Sundays 02:00"})

# Heroku Key-Value Store (Redis).
rule("redis", "read", "GET", RD, "credential", [CLI + "commands/redis/cli.ts", CLI + "lib/redis/api.ts"],
     card="Read Redis database {add_on_id_or_name}, with its password",
     notes="The response includes resource_url, the connection URL with the password; redis:cli connects with it.")
rule("redis", "update-config", "PATCH", RD + "/config", "write", [CLI + "commands/redis/maxmemory.ts", CLI + "commands/redis/timeout.ts",
     CLI + "commands/redis/keyspace-notifications.ts"],
     card="Change the configuration of Redis database {add_on_id_or_name}",
     when=[("{ arg: body.maxmemory_policy, matches: '^(?s:[^n].*|n[^o].*|no[^e].*|noe[^v].*|noev[^i].*|noevi[^c].*|noevic[^t].*|noevict[^i].*|noevicti[^o].*|noevictio[^n].*|noeviction.+|n|no|noe|noev|noevi|noevic|noevict|noevicti|noevictio|)$' }", "delete")],
     body={"timeout": 300},
     notes="Any maxmemory_policy but noeviction lets Redis evict keys when memory is full, deleting data.",
     tests=[("call", {"timeout": 300}, None, "write"),
            ("keep", {"maxmemory_policy": "noeviction"}, None, "write"),
            ("evict", {"maxmemory_policy": "allkeys-lru"}, None, "delete")])
rule("redis", "rotate-credentials", "POST", RD + "/credentials_rotation", "credential", CLI + "commands/redis/credentials.ts",
     card="Rotate the password of Redis database {add_on_id_or_name}", body={},
     notes="Sets a new password, a secret-store value.")
rule("redis", "stats-reset", "POST", RD + "/stats/reset", "write", CLI + "commands/redis/stats-reset.ts",
     card="Reset the statistics of Redis database {add_on_id_or_name}", body={})
rule("redis", "upgrade", "POST", RD + "/upgrade", "write", CLI + "commands/redis/upgrade.ts",
     card="Upgrade Redis database {add_on_id_or_name} to version {body.version}", body={"version": "7.2"},
     notes="Version upgrades keep the data.")
rule("redis", "wait", "GET", RD + "/wait", "read", CLI + "commands/redis/wait.ts")

# Everything else the Data API serves: unknown, so a read Opfence has not
# checked cannot return a password unnoticed.
for prefix in ("client", "postgres", "redis", "data"):
    rule("api", "other-" + prefix, "GET", "/" + prefix + "/{path*}", "unknown", CLI + "lib/data/base-command.ts", res=None,
         card="Read /" + prefix + "/{path} from the Heroku Data API",
         notes="A Data API read the Heroku CLI does not make. Many of the API's reads return passwords, so one "
               "Opfence has not checked is unknown rather than a read.",
         tests=[("call", None, None, "unknown")])

# Fixture paths and arguments.
SAMPLE = {"app_id_or_name": APP, "add_on_id_or_name": DB, "transfer": "b005", "link": "cache", "schedule": "3a0b7c1d-5e6f-4a8b-9c0d-1e2f3a4b5c6d",
          "credential": "analytics", "publication": "orders", "pool": "readers", "quota_type": "storage", "path*": "v11/databases/x/new_thing"}
SAMPLE_PER_GROUP = {"redis": {"add_on_id_or_name": REDIS}, "maintenance": {"add_on_id_or_name": DBNAME}}


def sample(path, group):
    vals = dict(SAMPLE, **SAMPLE_PER_GROUP.get(group, {}))
    return re.sub(r"\{([^}]+)\}", lambda m: vals[m.group(1)], path)


def fixture_name(r, suffix):
    return f"data-{r['group']}-{r['verb']}" + ("" if suffix == "call" else "-" + suffix) + ".http"


os.makedirs(D + "fixtures", exist_ok=True)
for f in os.listdir(D + "fixtures"):
    if f.startswith("data-"):
        os.remove(D + "fixtures/" + f)
for f in os.listdir(D):
    if f.startswith("data-") and f.endswith(".yaml"):
        os.remove(D + f)

TITLES = {"postgres": "Heroku Postgres (classic tiers): /client/v11 and /postgres/v0",
          "postgres-advanced": "Heroku Postgres Advanced: /data/postgres/v1",
          "maintenance": "database maintenance: /data/maintenances/v1",
          "redis": "Heroku Key-Value Store (Redis): /redis/v0",
          "api": "reads the Heroku CLI does not make"}
files = {}
ids = set()
for r in R:
    rid = f"heroku.data-{r['group']}.{r['verb']}"
    assert rid not in ids, rid
    ids.add(rid)
    L = files.setdefault(r["group"], [
        "# Heroku Data API (api.data.heroku.com), " + TITLES[r["group"]] + ".",
        "# Read from the Heroku CLI (heroku/cli at 65ca0bc, heroku-cli-util at 0ec7cba),",
        "# its only published client; the API has no published schema.",
        "operations:"])
    L.append(f"  - id: {rid}")
    L.append(f"    match: {{ rest: {{ method: {r['method']}, path: \"{r['path']}\" }} }}")
    L.append(f"    class: {r['cls']}")
    for cond, cls in r["when"]:
        if L[-1].startswith("    class:"):
            L.append("    when:")
        L.append(f"      - if: {cond}")
        L.append(f"        class: {cls}")
    res_arg = {"db": "add_on_id_or_name", "app": "app_id_or_name", None: None}[r["res"]]
    if res_arg and "{" + res_arg + "}" in r["path"]:
        kind = "add-on" if r["res"] == "db" else "app"
        L.append(f"    resource: {{ arg: {res_arg}, kind: {kind} }}")
    else:
        res_arg = None
    if r["card"]:
        L.append(f"    card: {json.dumps(r['card'])}")
    L.append("    status: verified")
    L.append("    verified: 2026-10-22")
    L.append(f"    unlisted: \"{UNLISTED}\"")
    L.append("    sources:")
    for s in r["src"]:
        L.append(f"      - {s}")
    if r["notes"]:
        L.append("    notes: >-")
        line = "      "
        for w in r["notes"].split():
            if len(line) + len(w) + 1 > 100 and line.strip():
                L.append(line)
                line = "      "
            line += ("" if line.strip() == "" else " ") + w
        L.append(line)
    L.append("    tests:")
    tests = r["tests"] or [("call", None, None, r["cls"])]
    for suffix, body, query, expect in tests:
        body = body if body is not None else r["body"]
        query = query if query is not None else r["query"]
        path = sample(r["fpath"] or r["path"], r["group"]) + ("?" + query if query else "")
        desc = (r["card"] or (r["method"] + " " + r["path"]))
        desc = re.sub(r"\{body\.([a-z_]+)\}", lambda m: str((body or {}).get(m.group(1), "")), desc)
        desc = re.sub(r"\{([^}]+)\}", lambda m: dict(SAMPLE, **SAMPLE_PER_GROUP.get(r["group"], {})).get(m.group(1), m.group(0)), desc)
        lines = [f"# description: {desc}" + ("" if suffix == "call" else f" ({suffix})"),
                 f"{r['method']} {path} HTTP/1.1",
                 "Host: api.data.heroku.com",
                 "Authorization: Bearer opf_heroku_EXAMPLE",
                 "Accept: application/vnd.heroku+json; version=3"]
        if body is not None and r["method"] != "GET":
            lines.append("Content-Type: application/json")
            lines.append("")
            lines.append(json.dumps(body))
        else:
            lines.append("")
        name = fixture_name(r, suffix)
        with open(D + "fixtures/" + name, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        L.append(f"      - fixture: fixtures/{name}")
        L.append(f"        expect: {expect}")
        if res_arg:
            L.append(f"        resource: \"{sample('{' + res_arg + '}', r['group'])}\"")
    L.append("")
for g, L in files.items():
    with open(D + f"data-{g}.yaml", "w") as fh:
        fh.write("\n".join(L))
print(len(R), "rules,", sum(len(r["tests"] or [1]) for r in R), "fixtures")
