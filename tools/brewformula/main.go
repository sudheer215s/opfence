// Command brewformula gives Formula/opfence.rb a release: the url of a
// tag's source archive and its SHA-256, so "brew install opfence" builds
// that release rather than needing --HEAD. Run it after pushing a tag:
//
//	go run ./tools/brewformula -tag v0.1.0
//
// It downloads the archive to hash it; -sha256 skips the download.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"regexp"
	"strings"
	"time"
)

var (
	tagRe    = regexp.MustCompile(`^v\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$`)
	shaRe    = regexp.MustCompile(`^[0-9a-f]{64}$`)
	urlLine  = regexp.MustCompile(`(?m)^  url "[^"\n]*"\n  sha256 "[^"\n]*"\n`)
	homeLine = regexp.MustCompile(`(?m)^  homepage "[^"\n]*"\n`)
)

// archiveURL is GitHub's source archive of a tag.
func archiveURL(repo, tag string) string {
	return "https://github.com/" + repo + "/archive/refs/tags/" + tag + ".tar.gz"
}

// setRelease puts url and sha256 into the formula: in place of the ones it
// has, or after its homepage.
func setRelease(formula, url, sum string) (string, error) {
	lines := fmt.Sprintf("  url %q\n  sha256 %q\n", url, sum)
	if urlLine.MatchString(formula) {
		return urlLine.ReplaceAllLiteralString(formula, lines), nil
	}
	loc := homeLine.FindStringIndex(formula)
	if loc == nil {
		return "", errors.New("the formula has no homepage line to put the url after")
	}
	return formula[:loc[1]] + lines + formula[loc[1]:], nil
}

func download(url string) (string, error) {
	c := &http.Client{Timeout: 2 * time.Minute}
	resp, err := c.Get(url)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("%s: %s", url, resp.Status)
	}
	h := sha256.New()
	if _, err := io.Copy(h, resp.Body); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func main() {
	tag := flag.String("tag", "", "release tag, such as v0.1.0")
	sum := flag.String("sha256", "", "the archive's SHA-256 (downloaded and hashed when empty)")
	repo := flag.String("repo", "sudheer215s/opfence", "GitHub repository the tag is in")
	file := flag.String("formula", "Formula/opfence.rb", "formula to update")
	flag.Parse()
	if !tagRe.MatchString(*tag) {
		log.Fatalf("-tag %q is not a release tag such as v0.1.0", *tag)
	}
	url := archiveURL(*repo, *tag)
	if *sum == "" {
		var err error
		if *sum, err = download(url); err != nil {
			log.Fatal(err)
		}
	}
	*sum = strings.ToLower(*sum)
	if !shaRe.MatchString(*sum) {
		log.Fatalf("-sha256 %q is not a SHA-256", *sum)
	}
	data, err := os.ReadFile(*file)
	if err != nil {
		log.Fatal(err)
	}
	out, err := setRelease(string(data), url, *sum)
	if err != nil {
		log.Fatal(err)
	}
	if err := os.WriteFile(*file, []byte(out), 0o644); err != nil {
		log.Fatal(err)
	}
	fmt.Printf("%s: %s\n  sha256 %s\n", *file, url, *sum)
}
