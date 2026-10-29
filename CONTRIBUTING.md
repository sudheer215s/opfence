# Contributing to Opfence

Thanks for helping. The most valuable contribution is a catalog rule: one tested fact about which API operation is dangerous.

## Adding a catalog rule

1. Find or create the provider folder under `catalog/<provider>/`.
2. Add the operation to a rule file (see [docs/ARCHITECTURE.md §4](docs/ARCHITECTURE.md#4-catalog) for the format).
3. Capture a fixture: the raw HTTP request (headers and body) saved as `fixtures/<name>.http`. Replace every real token with a placeholder such as `opf_railway_EXAMPLE`. With mitmproxy, use "Copy as raw request". For an MCP server that runs locally (no host), save the tool call instead as `fixtures/<name>.json`: `{"description": "...", "tool": "<tool name>", "arguments": {...}}`. For a message on a WebSocket (a GraphQL subscription socket), save the upgrade request followed by the messages the client sends, each after a line `>>> text` or `>>> binary`, as `fixtures/<name>.ws`; binary messages are written as Go string literals. The test checks the last message (see [docs/ARCHITECTURE.md §3.2](docs/ARCHITECTURE.md#32-request)).
4. Link a primary source (the provider's API reference, OpenAPI spec, GraphQL schema or MCP server source) in `sources`.
5. If the operation's response returns secrets next to ordinary data, add a `response` transform (see [docs/ARCHITECTURE.md §4.4](docs/ARCHITECTURE.md#44-conditional-classes)) and a recorded response, `fixtures/<name>-response.json`, named by the test's `response:` key. Every path must find something in it.
6. Run `opfence catalog validate` and `opfence test`.
7. If the provider publishes a machine-readable schema (OpenAPI, GraphQL, Heroku's hyper-schema, an AWS service model), list it under `schemas:` in `provider.yaml` and run `opfence catalog check-sources --provider <provider>`. It reports rules whose operation is not in the schema and non-read operations no rule covers. A rule for an endpoint the schema leaves out on purpose says why with `unlisted: <reason>`; until every non-read operation has a rule, mark the schema `coverage: partial` (see [docs/ARCHITECTURE.md §4.7](docs/ARCHITECTURE.md#47-drift-against-published-schemas)).

A rule can be `status: verified` only when it has a fixture, a source and a `verified` date; otherwise use `community` or `draft`.

Some providers are generated: Google Cloud, Supabase, GitLab, Terraform's MCP server and others, listed in [tools/catalog-gen](tools/catalog-gen/README.md). For those, change the script, run it, and commit both; an edit made only to a generated file is lost the next time the script runs.

## Code

- Go, formatted with `gofmt -s`. Run `make check` (format, vet, race tests) before opening a PR, and `make lint` for staticcheck.
- New dependencies need a reason in [docs/ARCHITECTURE.md §2](docs/ARCHITECTURE.md#dependencies). Fewer is better in a security tool.
- Decoders must fail closed: when unsure, emit an `unknown` operation, never `read`.
- Every behaviour change comes with a test.

## Releasing

1. Push a tag such as `v0.1.0`. The release workflow tests the tag, builds the binaries with GoReleaser and drafts a release with checksums and build provenance; publish the draft.
2. Run `go run ./tools/brewformula -tag v0.1.0`. It hashes the tag's source archive and gives `Formula/opfence.rb` its `url` and `sha256`, so `brew install opfence` builds the release. Open a PR with the change.

## Reporting security issues

See [SECURITY.md](SECURITY.md). Please do not open public issues for vulnerabilities, including rules that under-classify a dangerous operation.

## Licence

By contributing you agree that your contribution is licensed under the Apache License 2.0.
