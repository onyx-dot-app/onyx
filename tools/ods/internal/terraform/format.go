package terraform

import (
	"bytes"
	"fmt"
	"os"

	"github.com/hashicorp/hcl/v2"
	"github.com/hashicorp/hcl/v2/hclsyntax"
	"github.com/hashicorp/hcl/v2/hclwrite"
)

// FormatResult reports what one file needed.
type FormatResult struct {
	Path    string
	Changed bool
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
