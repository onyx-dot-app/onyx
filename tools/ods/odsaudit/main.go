// Command ods-audit is the vulnerability auditor of `ods`, shipped as its own
// binary. Its scanning stack (osv-scanner) is most of the size of a combined
// binary, so it is published as the separate `onyx-devtools[audit]` extra and
// `ods audit` forwards to it.
package main

import (
	"fmt"
	"os"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/auditcmd"
)

var (
	version = "dev"
	commit  = "none"
)

func main() {
	rootCmd := auditcmd.NewRootCommand(version, commit)

	if err := rootCmd.Execute(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(2)
	}
}
