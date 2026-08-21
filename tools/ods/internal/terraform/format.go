package terraform

import (
	"bytes"
	"fmt"
	"os"
	"runtime"
	"sync"

	"github.com/hashicorp/hcl/v2"
	"github.com/hashicorp/hcl/v2/hclsyntax"
	"github.com/hashicorp/hcl/v2/hclwrite"
)

// FormatResult reports what one file needed.
type FormatResult struct {
	Path    string
	Changed bool
}

// FormatFiles formats every file concurrently, bounded by GOMAXPROCS, and
// returns one result per input file in the same order as files. Each file is
// parsed and rewritten independently, so there is no reason to pay for that
// work one file at a time.
func FormatFiles(files []string, write bool) ([]FormatResult, []error) {
	results := make([]FormatResult, len(files))
	errs := make([]error, len(files))

	sem := make(chan struct{}, runtime.GOMAXPROCS(0))
	var wg sync.WaitGroup
	for i, file := range files {
		wg.Add(1)
		sem <- struct{}{}
		go func(i int, file string) {
			defer wg.Done()
			defer func() { <-sem }()
			results[i], errs[i] = FormatFile(file, write)
		}(i, file)
	}
	wg.Wait()

	return results, errs
}

// FormatFile canonicalises one Terraform file.
//
// It applies hclwrite.Format, the same routine `terraform fmt` uses, so the
// output matches terraform byte for byte without needing the binary. With
// write set, a file that differs is rewritten in place.
func FormatFile(path string, write bool) (FormatResult, error) {
	res := FormatResult{Path: path}

	src, err := os.ReadFile(path)
	if err != nil {
		return res, err
	}

	// Formatting invalid HCL would rewrite it into something worse, so refuse
	// the file instead. terraform fmt makes the same check.
	if _, diags := hclsyntax.ParseConfig(src, path, hcl.InitialPos); diags.HasErrors() {
		return res, fmt.Errorf("%s", diags.Error())
	}

	out := hclwrite.Format(src)
	if bytes.Equal(out, src) {
		return res, nil
	}
	res.Changed = true

	if !write {
		return res, nil
	}
	info, err := os.Stat(path)
	if err != nil {
		return res, err
	}
	if err := os.WriteFile(path, out, info.Mode().Perm()); err != nil {
		return res, err
	}
	return res, nil
}
