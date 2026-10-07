package auditcmd

import (
	"fmt"
	"io"
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

// editUI holds the interactive parts of the allowlist editor. Commands pass
// terminalEditUI; tests pass fakes because the real editor needs a terminal.
type editUI struct {
	// edit opens the row editor and reports the edited rows and whether the
	// user saved.
	edit func(title string, cols []tui.Column, rows []map[string]string) ([]map[string]string, bool, error)
	// confirm asks a yes/no question and reports the answer.
	confirm func(prompt string) bool
}

func terminalEditUI() editUI {
	return editUI{edit: tui.EditRows, confirm: prompt.Confirm}
}

// newAuditIgnoreCommand creates the `ods audit ignore` command group. Running it
// bare opens the allowlist editor, the same as `ods audit ignore edit`.
func newAuditIgnoreCommand(ui editUI) *cobra.Command {
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
			exitOnError(runAuditEdit(opts.IgnoreURL, cmd.OutOrStdout(), ui))
		},
	}

	// A persistent flag so both the bare command and its subcommands share it.
	cmd.PersistentFlags().StringVar(&opts.IgnoreURL, "ignore-url", audit.DefaultIgnoreURL, "S3 URL or local path of the advisory allowlist")

	cmd.AddCommand(newAuditIgnoreEditCommand(opts, ui))
	cmd.AddCommand(newAuditIgnoreAddCommand(opts))

	return cmd
}

// newAuditIgnoreEditCommand creates the `ods audit ignore edit` subcommand. It
// shares the parent's --ignore-url via the passed options.
func newAuditIgnoreEditCommand(opts *AuditIgnoreOptions, ui editUI) *cobra.Command {
	return &cobra.Command{
		Use:   "edit",
		Short: "Edit the audit advisory allowlist in a TUI",
		Long: `Edit the audit advisory allowlist.

Fetches the allowlist (from S3 by default), opens a terminal table where you can
add, edit, and delete suppressions, then uploads the result back after a
confirmation prompt.`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			exitOnError(runAuditEdit(opts.IgnoreURL, cmd.OutOrStdout(), ui))
		},
	}
}

// runAuditEdit fetches the allowlist at url, lets the user edit it in ui, and
// saves the result after confirmation. Without a usable editor it prints the
// allowlist instead.
func runAuditEdit(url string, out io.Writer, ui editUI) error {
	orig, err := audit.LoadIgnoresForEdit(url)
	if err != nil {
		return failf("Failed to fetch allowlist from %s: %v", url, err)
	}

	rows := make([]map[string]string, len(orig))
	for i, e := range orig {
		rows[i] = entryToRow(e)
	}

	cols := ignoreColumns(gitUserEmail())

	editedRows, saved, err := ui.edit("Audit allowlist — "+url, cols, rows)
	if err != nil {
		// No usable terminal (e.g. piped input): show a read-only dump instead of
		// crashing, and leave the allowlist untouched.
		log.Debugf("TUI editor unavailable: %v", err)
		printIgnores(out, orig)
		log.Warnf("An interactive terminal is required to edit; edit %s manually.", url)
		return nil
	}
	if !saved {
		_, _ = fmt.Fprintln(out, "No changes made.")
		return nil
	}

	edited := make([]audit.IgnoreEntry, len(editedRows))
	for i, r := range editedRows {
		e := rowToEntry(r)
		if err := audit.ValidateEntry(e); err != nil {
			return failf("Invalid allowlist entry %q: %v", e.ID, err)
		}
		edited[i] = e
	}
	audit.SortIgnores(edited)

	if dups := audit.DuplicateKeys(edited); len(dups) > 0 {
		log.Errorf("Duplicate entries (id + ecosystem): %s", strings.Join(dups, ", "))
		_, _ = fmt.Fprintln(out, "Nothing uploaded; remove the duplicates and try again.")
		return nil
	}

	added, removed, changed := audit.DiffIgnores(orig, edited)
	if len(added) == 0 && len(removed) == 0 && len(changed) == 0 {
		_, _ = fmt.Fprintln(out, "No changes to save.")
		return nil
	}

	printDiff(out, added, removed, changed)

	if !ui.confirm(fmt.Sprintf("Upload updated allowlist (%d entries) to %s? [Y/n] ", len(edited), url)) {
		_, _ = fmt.Fprintln(out, "Aborted; nothing uploaded.")
		return nil
	}

	if err := audit.SaveIgnores(url, edited); err != nil {
		return failf("Failed to save allowlist: %v", err)
	}
	_, _ = fmt.Fprintf(out, "Uploaded %d entries to %s\n", len(edited), url)
	return nil
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

func printIgnores(out io.Writer, entries []audit.IgnoreEntry) {
	if len(entries) == 0 {
		_, _ = fmt.Fprintln(out, "Allowlist is empty.")
		return
	}
	_, _ = fmt.Fprintf(out, "Allowlist (%d entries):\n", len(entries))
	for _, e := range entries {
		_, _ = fmt.Fprintf(out, "  - %s\n", formatEntry(e))
	}
}

func printDiff(out io.Writer, added, removed, changed []audit.IgnoreEntry) {
	_, _ = fmt.Fprintln(out, "Changes:")
	for _, e := range added {
		_, _ = fmt.Fprintf(out, "  + %s\n", formatEntry(e))
	}
	for _, e := range removed {
		_, _ = fmt.Fprintf(out, "  - %s\n", formatEntry(e))
	}
	for _, e := range changed {
		_, _ = fmt.Fprintf(out, "  ~ %s\n", formatEntry(e))
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
