package decode

import (
	"bytes"
	"encoding/json"
	"errors"
	"net/url"
	"strconv"
	"strings"

	"github.com/rakeshnitb23/opfence/internal/request"
)

// Git services, in Operation.Service.
const (
	GitUploadPack  = "upload-pack"  // fetch and clone
	GitReceivePack = "receive-pack" // push
	GitLFS         = "lfs"          // Git LFS batch and locks APIs
)

// Git commands, in Operation.Action.
const (
	GitFetch     = "fetch"      // upload-pack, any request
	GitListRefs  = "list"       // receive-pack ref advertisement, or a push with no ref updates
	GitCreate    = "create"     // receive-pack: a new ref
	GitUpdate    = "update"     // receive-pack: an existing ref moved (fast-forward or forced)
	GitDelete    = "delete"     // receive-pack: a ref removed
	LFSDownload  = "download"   // LFS batch
	LFSUpload    = "upload"     // LFS batch
	LFSListLocks = "list-locks" // LFS locks list or verify
	LFSLock      = "lock"       // LFS lock create
	LFSUnlock    = "unlock"     // LFS lock delete
)

// maxPktLine is the largest pkt-line git sends (LARGE_PACKET_MAX).
const maxPktLine = 65520

// isGitPath reports whether a request path is git's smart HTTP protocol or
// the Git LFS API under a repository: /{owner}/{repo}/info/refs,
// /git-upload-pack, /git-receive-pack or /info/lfs/..., where the owner may
// be several segments (GitLab's nested groups: /group/sub/project.git/...).
func isGitPath(rawPath string) bool {
	_, _, ok := gitSplit(rawPath)
	return ok
}

// gitSplit splits a git request path, unescaped, into the repository's
// segments (the owner, possibly nested, and the repository) and the git part
// after them. The git part is the path's end for the smart HTTP protocol;
// for Git LFS it starts at info/lfs, and a path with two such places is
// ambiguous and not git.
//
// A repository two segments deep (GitHub's /owner/repo) may leave out .git.
// A deeper one (GitLab's /group/sub/project.git) must end in .git, as
// GitLab requires (it redirects the path without it): gitlab.com serves its
// API on the same host, and POST /api/v4/projects/1/repository/files/
// git-upload-pack is a REST call that creates a file, not a fetch.
func gitSplit(rawPath string) (repo, rest []string, ok bool) {
	segs, ok := gitSegments(rawPath)
	if !ok {
		return nil, nil, false
	}
	n := len(segs)
	valid := func(repo []string) bool {
		return len(repo) == 2 || len(repo) > 2 && strings.HasSuffix(repo[len(repo)-1], ".git")
	}
	switch {
	case n >= 3 && (segs[n-1] == "git-upload-pack" || segs[n-1] == "git-receive-pack"):
		return segs[:n-1], segs[n-1:], valid(segs[:n-1])
	case n >= 4 && segs[n-2] == "info" && segs[n-1] == "refs":
		return segs[:n-2], segs[n-2:], valid(segs[:n-2])
	}
	k := -1
	for i := 2; i+1 < n; i++ {
		if segs[i] == "info" && segs[i+1] == "lfs" {
			if k >= 0 {
				return nil, nil, false
			}
			k = i
		}
	}
	if k < 0 {
		return nil, nil, false
	}
	return segs[:k], segs[k:], valid(segs[:k])
}

// gitSegments returns the path's segments, unescaped.
func gitSegments(rawPath string) ([]string, bool) {
	segs, ok := request.NormalizePath(rawPath)
	if !ok {
		return nil, false
	}
	for i, s := range segs {
		d, err := url.PathUnescape(s)
		if err != nil {
			return nil, false
		}
		segs[i] = d
	}
	return segs, true
}

func decodeGit(r *request.Request) []Operation {
	repoSegs, segs, _ := gitSplit(r.Path)
	owner := strings.Join(repoSegs[:len(repoSegs)-1], "/")
	repo := strings.TrimSuffix(repoSegs[len(repoSegs)-1], ".git")
	repoArgs := func() map[string]any {
		return map[string]any{"owner": owner, "repo": repo, "repository": owner + "/" + repo}
	}
	op := Operation{Protocol: Git, Method: r.Method, Path: r.Path, Args: repoArgs()}
	fail := func(msg string) []Operation {
		op.Error = msg
		return []Operation{op}
	}
	readOnly := r.Method == "GET" || r.Method == "HEAD"
	switch {
	case segs[0] == "info" && segs[1] == "refs":
		if !readOnly {
			return fail("git ref advertisement must be a GET")
		}
		switch r.Query.Get("service") {
		case "git-upload-pack", "":
			// No service is git's dumb protocol, which only reads files.
			op.Service, op.Action = GitUploadPack, GitFetch
		case "git-receive-pack":
			op.Service, op.Action = GitReceivePack, GitListRefs
		default:
			return fail("unknown git service " + strconv.Quote(r.Query.Get("service")))
		}
		return []Operation{op}
	case segs[0] == "git-upload-pack":
		if r.Method != "POST" {
			return fail("git-upload-pack must be a POST")
		}
		// Every upload-pack request, in any protocol version, only reads.
		op.Service, op.Action = GitUploadPack, GitFetch
		return []Operation{op}
	case segs[0] == "git-receive-pack":
		if r.Method != "POST" {
			return fail("git-receive-pack must be a POST")
		}
		op.Service = GitReceivePack
		body := r.Body
		if r.BodyErr != nil {
			// The pack follows the commands and is usually larger than
			// MaxBody; the commands themselves fit in its first bytes.
			if !errors.Is(r.BodyErr, request.ErrBodyTooLarge) || r.Header.Get("Content-Encoding") != "" {
				return fail("git push body could not be read: " + r.BodyErr.Error())
			}
			body = r.Prefix
		}
		cmds, err := parseReceivePack(body)
		if err != nil {
			return fail("git push: " + err.Error())
		}
		if len(cmds) == 0 {
			// git sends a push with no ref updates to probe authentication
			// before a large upload.
			op.Action = GitListRefs
			return []Operation{op}
		}
		ops := make([]Operation, 0, len(cmds))
		for _, c := range cmds {
			o := op
			o.Action = c.action
			o.Args = repoArgs()
			o.Args["ref"], o.Args["old"], o.Args["new"] = c.ref, c.old, c.new
			ops = append(ops, o)
		}
		return ops
	}
	// Git LFS: /{owner}/{repo}/info/lfs/...
	op.Service = GitLFS
	lfs := segs[2:]
	switch {
	case len(lfs) == 2 && lfs[0] == "objects" && lfs[1] == "batch" && r.Method == "POST":
		var batch struct {
			Operation string `json:"operation"`
		}
		if r.BodyErr != nil {
			return fail("LFS batch body could not be read: " + r.BodyErr.Error())
		}
		if err := json.Unmarshal(r.Body, &batch); err != nil {
			return fail("LFS batch body is not JSON")
		}
		switch batch.Operation {
		case LFSDownload, LFSUpload:
			op.Action = batch.Operation
		default:
			return fail("unknown LFS batch operation " + strconv.Quote(batch.Operation))
		}
	case len(lfs) == 1 && lfs[0] == "locks" && readOnly,
		len(lfs) == 2 && lfs[0] == "locks" && lfs[1] == "verify" && r.Method == "POST":
		op.Action = LFSListLocks
	case len(lfs) == 1 && lfs[0] == "locks" && r.Method == "POST":
		op.Action = LFSLock
		var lock struct {
			Path string `json:"path"`
		}
		if r.BodyErr == nil && json.Unmarshal(r.Body, &lock) == nil && lock.Path != "" {
			op.Args["path"] = lock.Path
		}
	case len(lfs) == 3 && lfs[0] == "locks" && lfs[2] == "unlock" && r.Method == "POST":
		op.Action = LFSUnlock
		op.Args["id"] = lfs[1]
	default:
		return fail("unknown Git LFS request " + r.Method + " " + strings.Join(lfs, "/"))
	}
	return []Operation{op}
}

type refCommand struct {
	action, ref, old, new string
}

// parseReceivePack reads the ref update commands at the start of a
// git-receive-pack request: pkt-lines of "<old> <new> <ref>", the first
// followed by NUL and capabilities, ended by a flush packet. Shallow lines
// may come first. Push options and the pack that follow are not read.
func parseReceivePack(b []byte) ([]refCommand, error) {
	var cmds []refCommand
	for first := true; ; first = false {
		if len(b) < 4 {
			return nil, errors.New("the ref updates end before their flush packet")
		}
		n, err := strconv.ParseUint(string(b[:4]), 16, 16)
		if err != nil {
			return nil, errors.New("malformed pkt-line length")
		}
		if n == 0 {
			return cmds, nil
		}
		if n < 5 || n > maxPktLine {
			return nil, errors.New("unexpected pkt-line length " + string(b[:4]))
		}
		if int(n) > len(b) {
			return nil, errors.New("the ref updates end before their flush packet")
		}
		line := b[4:n]
		b = b[n:]
		if first {
			if i := bytes.IndexByte(line, 0); i >= 0 {
				line = line[:i]
			}
		}
		line = bytes.TrimSuffix(line, []byte("\n"))
		s := string(line)
		switch {
		case strings.HasPrefix(s, "shallow ") && len(cmds) == 0:
			continue
		case strings.HasPrefix(s, "push-cert"):
			return nil, errors.New("signed pushes are not decoded")
		}
		c, err := parseRefCommand(s)
		if err != nil {
			return nil, err
		}
		cmds = append(cmds, c)
	}
}

func parseRefCommand(s string) (refCommand, error) {
	parts := strings.Split(s, " ")
	if len(parts) != 3 {
		return refCommand{}, errors.New("malformed ref update " + strconv.Quote(s))
	}
	old, nw, ref := parts[0], parts[1], parts[2]
	if !isObjectID(old) || !isObjectID(nw) || len(old) != len(nw) {
		return refCommand{}, errors.New("malformed object id in " + strconv.Quote(s))
	}
	if !strings.HasPrefix(ref, "refs/") || strings.ContainsAny(ref, "\x00\x7f\\:?*[^~ \t") || strings.Contains(ref, "..") {
		return refCommand{}, errors.New("invalid ref name " + strconv.Quote(ref))
	}
	c := refCommand{ref: ref, old: old, new: nw}
	zero := strings.Repeat("0", len(old))
	switch {
	case old == zero && nw == zero:
		return refCommand{}, errors.New("ref update with two zero ids")
	case old == zero:
		c.action = GitCreate
	case nw == zero:
		c.action = GitDelete
	default:
		c.action = GitUpdate
	}
	return c, nil
}

// isObjectID reports whether s is a SHA-1 or SHA-256 object id in lower-case
// hex.
func isObjectID(s string) bool {
	if len(s) != 40 && len(s) != 64 {
		return false
	}
	for i := 0; i < len(s); i++ {
		if c := s[i]; (c < '0' || c > '9') && (c < 'a' || c > 'f') {
			return false
		}
	}
	return true
}

// GitPushCapabilities returns the capabilities a git-receive-pack request
// asks for, from its first command line.
func GitPushCapabilities(r *request.Request) []string {
	b := r.Body
	if r.BodyErr != nil {
		b = r.Prefix
	}
	for len(b) >= 4 {
		n, err := strconv.ParseUint(string(b[:4]), 16, 16)
		if err != nil || n < 5 || int(n) > len(b) {
			return nil
		}
		line := string(b[4:n])
		b = b[n:]
		if strings.HasPrefix(line, "shallow ") {
			continue
		}
		_, caps, ok := strings.Cut(strings.TrimSuffix(line, "\n"), "\x00")
		if !ok {
			return nil
		}
		return strings.Fields(caps)
	}
	return nil
}
