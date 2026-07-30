package cmd

import (
	"fmt"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/prompt"
)

// AuditIgnoreAddOptions holds options for `ods audit ignore add`.
type AuditIgnoreAddOptions struct {
	Ecosystem string
	Reason    string
	Expires   string
	AddedBy   string
	Yes       bool
}

// newAuditIgnoreAddCommand creates the `ods audit ignore add` subcommand: a
// non-interactive way to append one suppression to the allowlist. It shares the
// parent's --ignore-url via the passed options.
func newAuditIgnoreAddCommand(parent *AuditIgnoreOptions) *cobra.Command {
	opts := &AuditIgnoreAddOptions{}

	cmd := &cobra.Command{
		Use:   "add <id>",
		Short: "Add a suppression to the audit advisory allowlist",
		Long: `Add a single suppression to the audit advisory allowlist without opening the editor.

<id> is the advisory id (e.g. GHSA-xxxx-xxxx-xxxx or CVE-2023-1234); it matches a
finding's id or any of its aliases. A --reason is required so every suppression
records why the advisory was accepted, and --added-by defaults to your git email.
The updated allowlist is uploaded to S3 (shared by the whole team) after a diff
and a confirmation prompt; pass --yes to skip the prompt in automation.

Suppress only advisories you've reviewed and accepted — this allowlist gates
every deploy.`,
		Args: cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			runAuditIgnoreAdd(args[0], parent.IgnoreURL, opts)
		},
	}

	cmd.Flags().StringVar(&opts.Ecosystem, "ecosystem", "", "Restrict the suppression to this ecosystem (e.g. npm, PyPI, Debian:12)")
	cmd.Flags().StringVar(&opts.Reason, "reason", "", "Why the advisory is accepted (required)")
	cmd.Flags().StringVar(&opts.Expires, "expires", "", "Inclusive expiry date YYYY-MM-DD; omit for no expiry")
	cmd.Flags().StringVar(&opts.AddedBy, "added-by", "", "Who added the suppression (defaults to git user email)")
	cmd.Flags().BoolVar(&opts.Yes, "yes", false, "Skip the confirmation prompt")

	return cmd
}

func runAuditIgnoreAdd(id, url string, opts *AuditIgnoreAddOptions) {
	// A reason is mandatory: it's the record of why an advisory was accepted and
	// the main guardrail against casually burying a real issue.
	if strings.TrimSpace(opts.Reason) == "" {
		log.Fatal("A --reason is required to suppress an advisory")
	}

	addedBy := opts.AddedBy
	if addedBy == "" {
		addedBy = gitUserEmail()
	}

	entry := audit.IgnoreEntry{
		ID:        strings.TrimSpace(id),
		Ecosystem: strings.TrimSpace(opts.Ecosystem),
		Reason:    strings.TrimSpace(opts.Reason),
		AddedBy:   addedBy,
		Expires:   strings.TrimSpace(opts.Expires),
	}
	if err := audit.ValidateEntry(entry); err != nil {
		log.Fatalf("Invalid suppression: %v", err)
	}

	// Use FetchIgnores, not LoadIgnoresForEdit: a missing local file must error
	// rather than bootstrap an empty list. Unlike the interactive editor (which
	// shows the empty table), a typo'd --ignore-url here would silently append to
	// a fresh file and drop the real allowlist's entries on save.
	orig, err := audit.FetchIgnores(url)
	if err != nil {
		log.Fatalf("Failed to fetch allowlist from %s: %v", url, err)
	}

	edited := append(append([]audit.IgnoreEntry{}, orig...), entry)
	// A colliding id+ecosystem would silently collapse on save; surface it and
	// point at the editor rather than overwriting the existing reason/expiry.
	if dups := audit.DuplicateKeys(edited); len(dups) > 0 {
		log.Fatalf("An allowlist entry for %s already exists; update it with `ods audit ignore edit`", strings.Join(dups, ", "))
	}
	audit.SortIgnores(edited)

	added, removed, changed := audit.DiffIgnores(orig, edited)
	printDiff(added, removed, changed)

	if !opts.Yes && !prompt.Confirm(fmt.Sprintf("Upload updated allowlist (%d entries) to %s? [Y/n] ", len(edited), url)) {
		fmt.Println("Aborted; nothing uploaded.")
		return
	}

	if err := audit.SaveIgnores(url, edited); err != nil {
		log.Fatalf("Failed to save allowlist: %v", err)
	}
	fmt.Printf("Uploaded %d entries to %s\n", len(edited), url)
}
