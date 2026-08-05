package cmd

import (
	"fmt"
	"os/exec"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/prompt"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/tui"
)

// AuditIgnoreOptions holds options shared by the `ods audit ignore` commands.
type AuditIgnoreOptions struct {
	IgnoreURL string
}

// newAuditIgnoreCommand creates the `ods audit ignore` command group. Running it
// bare opens the allowlist editor, the same as `ods audit ignore edit`.
func newAuditIgnoreCommand() *cobra.Command {
	opts := &AuditIgnoreOptions{}

	cmd := &cobra.Command{
		Use:   "ignore",
		Short: "Manage the audit advisory allowlist",
		Long: `Manage the audit advisory allowlist (the suppressions applied by "ods audit").

Run bare to open the interactive editor, or use a subcommand. The allowlist is
fetched from S3 by default; pass a local file path to --ignore-url to edit a file
on disk instead.`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			runAuditEdit(opts.IgnoreURL)
		},
	}

	// A persistent flag so both the bare command and its subcommands share it.
	cmd.PersistentFlags().StringVar(&opts.IgnoreURL, "ignore-url", audit.DefaultIgnoreURL, "S3 URL or local path of the advisory allowlist")

	cmd.AddCommand(newAuditIgnoreEditCommand(opts))
	cmd.AddCommand(newAuditIgnoreAddCommand(opts))

	return cmd
}

// newAuditIgnoreEditCommand creates the `ods audit ignore edit` subcommand. It
// shares the parent's --ignore-url via the passed options.
func newAuditIgnoreEditCommand(opts *AuditIgnoreOptions) *cobra.Command {
	return &cobra.Command{
		Use:   "edit",
		Short: "Edit the audit advisory allowlist in a TUI",
		Long: `Edit the audit advisory allowlist.

Fetches the allowlist (from S3 by default), opens a terminal table where you can
add, edit, and delete suppressions, then uploads the result back after a
confirmation prompt.`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			runAuditEdit(opts.IgnoreURL)
		},
	}
}

func runAuditEdit(url string) {
	orig, err := audit.LoadIgnoresForEdit(url)
	if err != nil {
		log.Fatalf("Failed to fetch allowlist from %s: %v", url, err)
	}

	rows := make([]map[string]string, len(orig))
	for i, e := range orig {
		rows[i] = entryToRow(e)
	}

	cols := ignoreColumns(gitUserEmail())

	editedRows, saved, err := tui.EditRows("Audit allowlist — "+url, cols, rows)
	if err != nil {
		// No usable terminal (e.g. piped input): show a read-only dump instead of
		// crashing, and leave the allowlist untouched.
		log.Debugf("TUI editor unavailable: %v", err)
		printIgnores(orig)
		log.Warnf("An interactive terminal is required to edit; edit %s manually.", url)
		return
	}
	if !saved {
		fmt.Println("No changes made.")
		return
	}

	edited := make([]audit.IgnoreEntry, len(editedRows))
	for i, r := range editedRows {
		e := rowToEntry(r)
		if err := audit.ValidateEntry(e); err != nil {
			log.Fatalf("Invalid allowlist entry %q: %v", e.ID, err)
		}
		edited[i] = e
	}
	audit.SortIgnores(edited)

	if dups := audit.DuplicateKeys(edited); len(dups) > 0 {
		log.Errorf("Duplicate entries (id + ecosystem): %s", strings.Join(dups, ", "))
		fmt.Println("Nothing uploaded; remove the duplicates and try again.")
		return
	}

	added, removed, changed := audit.DiffIgnores(orig, edited)
	if len(added) == 0 && len(removed) == 0 && len(changed) == 0 {
		fmt.Println("No changes to save.")
		return
	}

	printDiff(added, removed, changed)

	if !prompt.Confirm(fmt.Sprintf("Upload updated allowlist (%d entries) to %s? [Y/n] ", len(edited), url)) {
		fmt.Println("Aborted; nothing uploaded.")
		return
	}

	if err := audit.SaveIgnores(url, edited); err != nil {
		log.Fatalf("Failed to save allowlist: %v", err)
	}
	fmt.Printf("Uploaded %d entries to %s\n", len(edited), url)
}

// ignoreColumns is the table/form schema for an IgnoreEntry. defaultAddedBy
// prefills the "Added By" field of newly added entries.
func ignoreColumns(defaultAddedBy string) []tui.Column {
	return []tui.Column{
		{Key: "id", Title: "ID", Required: true},
		{Key: "ecosystem", Title: "Ecosystem"},
		{Key: "reason", Title: "Reason"},
		{Key: "added_by", Title: "Added By", Default: defaultAddedBy},
		{Key: "expires", Title: "Expires", Validate: audit.ValidateExpires},
	}
}

func entryToRow(e audit.IgnoreEntry) map[string]string {
	return map[string]string{
		"id":        e.ID,
		"ecosystem": e.Ecosystem,
		"reason":    e.Reason,
		"added_by":  e.AddedBy,
		"expires":   e.Expires,
	}
}

func rowToEntry(r map[string]string) audit.IgnoreEntry {
	return audit.IgnoreEntry{
		ID:        r["id"],
		Ecosystem: r["ecosystem"],
		Reason:    r["reason"],
		AddedBy:   r["added_by"],
		Expires:   r["expires"],
	}
}

func printIgnores(entries []audit.IgnoreEntry) {
	if len(entries) == 0 {
		fmt.Println("Allowlist is empty.")
		return
	}
	fmt.Printf("Allowlist (%d entries):\n", len(entries))
	for _, e := range entries {
		fmt.Printf("  - %s\n", formatEntry(e))
	}
}

func printDiff(added, removed, changed []audit.IgnoreEntry) {
	fmt.Println("Changes:")
	for _, e := range added {
		fmt.Printf("  + %s\n", formatEntry(e))
	}
	for _, e := range removed {
		fmt.Printf("  - %s\n", formatEntry(e))
	}
	for _, e := range changed {
		fmt.Printf("  ~ %s\n", formatEntry(e))
	}
}

func formatEntry(e audit.IgnoreEntry) string {
	parts := []string{e.ID}
	if e.Ecosystem != "" {
		parts = append(parts, "eco="+e.Ecosystem)
	}
	if e.Expires != "" {
		parts = append(parts, "expires="+e.Expires)
	}
	if e.AddedBy != "" {
		parts = append(parts, "by="+e.AddedBy)
	}
	if e.Reason != "" {
		parts = append(parts, "reason="+e.Reason)
	}
	return strings.Join(parts, "  ")
}

// gitUserEmail returns the configured git user email, or "" if unavailable.
func gitUserEmail() string {
	out, err := exec.Command("git", "config", "user.email").Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}
