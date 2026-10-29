# Catalog generators

These scripts wrote the catalog's generated providers. Each holds the reviewed decisions (a class for every operation, the notes and the arguments that make a call stricter) and turns a provider's published description into rules and fixtures, so a new version of the description can be compared with the catalog by running the script again and reading `git diff`.

Run them from the repository root with Python 3 (`-I` keeps the interpreter from loading modules from the input's folder). `appservicesgen.py` and `gitlabgen.py` (for a YAML input) need PyYAML. Each one rewrites the files it owns, fixtures included, so run it on a clean tree.

| Script | Writes | Input |
| --- | --- | --- |
| `gcpgen.py` | the 20 `catalog/google-cloud-*` providers, from Google's discovery documents (`python3 -I tools/catalog-gen/gcpgen.py <folder> [provider ids]`) | a folder with one `<api>_<version>.json` per API version the script lists: `https://www.googleapis.com/discovery/v1/apis/<api>/<version>/rest`, or the API's own host for `iam` v2, `run` v2 and `cloudfunctions` v2 (`https://<api>.googleapis.com/$discovery/rest?version=v2`) |
| `cfgen.py` | `catalog/cloudflare`'s API Shield, Zero Trust device, DLP, Magic and Cloudforce One families, for operations no rule covers yet (added at the end of their family's file); `--print` lists them instead | `openapi.json` from [cloudflare/api-schemas](https://github.com/cloudflare/api-schemas) |
| `supabasegen.py` | `catalog/supabase` (the Management API) | `https://api.supabase.com/api/v1-json` |
| `sbprojectgen.py` | `catalog/supabase-project` (each project's REST, storage, auth, functions and realtime APIs) | none; the realtime socket's rules, written by hand in stage 28c, are kept in `sbproject-realtime-socket.yaml` and appended, and their `realtime-socket-*` fixtures are left alone |
| `herokudatagen.py` | `catalog/heroku/data-*.yaml` (Heroku's Data API, read from the Heroku CLI) | none |
| `tfgen.py` | `catalog/terraform-mcp` | a checkout of [hashicorp/terraform-mcp-server](https://github.com/hashicorp/terraform-mcp-server) |
| `appservicesgen.py` | `catalog/atlas-app-services` | `openapi-admin-v3.yaml` from [mongodb/docs](https://github.com/mongodb/docs/blob/main/content/app-services/source/openapi-admin-v3.yaml) |
| `copilotgen.py` | `catalog/github-mcp/copilot-api.yaml` (the Copilot API on GitHub's MCP host) | none |
| `pgfix.py` | `neon-sql`'s Postgres-over-WebSocket fixtures (`python3 -I tools/catalog-gen/pgfix.py catalog/neon-sql/fixtures`) | none; `socket-connect.http` is written by hand |
| `gitlabstatic.py`, `gitlabgen.py`, `gitlabmcp.py` | `catalog/gitlab`: the git and OAuth rules; the REST rules (`gitlabgen.py <openapi_v3.json or .yaml> <GitLab commit>`); the MCP server's tools (`gitlabmcp.py <GitLab commit>`). Run them in that order | `doc/api/openapi/openapi_v3.yaml` from [gitlab-org/gitlab](https://gitlab.com/gitlab-org/gitlab) at the commit given; the MCP tools were read from the same commit's source |

## Checked on 29 October 2026

Every script reproduces its files byte for byte: those without inputs, `gitlabgen.py` with the description at the commit the catalog names (4addde3db6991438aa04abeb14368a466eb046c0), and `supabasegen.py`, `appservicesgen.py`, `tfgen.py`, `gcpgen.py` and `cfgen.py` with that day's published descriptions, apart from two changes in them since the catalog was generated: Cloudflare's has four new Cloudforce One operations, and Cloud SQL's stops a workload-capture replay on the instance (`workloadCaptures:stopReplay`) rather than on one capture, which `opfence catalog check-sources` reports as one stale rule and one uncovered operation per API version. Neither change is in the catalog yet; the regenerated Cloud SQL card needs rewording first.
