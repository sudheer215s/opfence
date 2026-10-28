package drift

import (
	"context"
	"slices"
	"testing"
	"testing/fstest"

	"github.com/rakeshnitb23/opfence/internal/catalog"
)

func TestOptionalSegments(t *testing.T) {
	cases := map[string][]string{
		"/groups/{id}/(-/)epics":                  {"/groups/{id}/epics", "/groups/{id}/-/epics"},
		"/a/(x/)b/(y/)c":                          {"/a/b/c", "/a/x/b/c", "/a/b/y/c", "/a/x/b/y/c"},
		"/nuget/Packages(Id='{n}',Version='{v}')": {"/nuget/Packages(Id='{n}',Version='{v}')"},
		"/nuget/FindPackagesById()":               {"/nuget/FindPackagesById()"},
		"/plain/{id}":                             {"/plain/{id}"},
	}
	for in, want := range cases {
		if got := optionalSegments(in); !slices.Equal(got, want) {
			t.Errorf("optionalSegments(%q) = %q, want %q", in, got, want)
		}
	}
}

// A Grape spec (GitLab's) is checked with its optional segments expanded,
// and its MCP endpoint, on the REST API's host, is covered by the tool rules.
func TestGrapeSpec(t *testing.T) {
	const prov = `provider: forge
title: Forge
hosts: [forge.example]
defaults: { rest_safe_methods: read }
mcp:
  names: [forge]
  paths: [/api/v4/mcp]
schemas:
  - kind: openapi
    url: https://forge.example/openapi.yaml
`
	const rules = `operations:
  - id: forge.epic.create
    match: { rest: { method: POST, path: "/api/v4/groups/{id}/epics" } }
    class: write
    card: "Do it"
    status: community
  - id: forge.epic.create-dash
    match: { rest: { method: POST, path: "/api/v4/groups/{id}/-/epics" } }
    class: write
    card: "Do it"
    status: community
  - id: forge.label.delete
    match: { rest: { method: DELETE, path: "/api/v4/groups/{id}/labels" } }
    class: delete
    card: "Do it"
    status: community
  - id: forge.mcp.run
    match: { mcp: { tool: run } }
    class: write
    card: "Do it"
    status: community
`
	const spec = `openapi: 3.0.0
servers:
  - url: https://{hostname}
    variables: { hostname: { default: forge.example } }
paths:
  /api/v4/groups/{id}/(-/)epics:
    post: {}
  /api/v4/groups/{id}/(-/)labels:
    delete: {}
  /api/v4/mcp:
    get: {}
    post: {}
`
	c, err := catalog.Load(fstest.MapFS{
		"forge/provider.yaml": {Data: []byte(prov)},
		"forge/rules.yaml":    {Data: []byte(rules)},
		"embed.go":            {Data: []byte("package catalog")},
	})
	if err != nil {
		t.Fatal(err)
	}
	r := CheckProvider(context.Background(), c.Providers[0], fakeFetcher(map[string]string{"https://forge.example/openapi.yaml": spec}))
	if r.Err != nil {
		t.Fatal(r.Err)
	}
	if r.Ops != 6 {
		t.Errorf("ops = %d, want 6 (two forms of each Grape path, and the MCP endpoint's two)", r.Ops)
	}
	if len(r.Stale) != 0 {
		t.Errorf("stale = %v", ids(r.Stale))
	}
	// The labels rule covers one form; the other is uncovered. POST
	// /api/v4/mcp is under the MCP path, so the tool rules cover it.
	if got, want := ids(r.Uncovered), []string{"DELETE /api/v4/groups/{id}/-/labels"}; !slices.Equal(got, want) {
		t.Errorf("uncovered = %v, want %v", got, want)
	}
}
