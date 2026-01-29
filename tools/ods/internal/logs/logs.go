package logs

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"os/exec"
	"regexp"
	"sort"
	"strings"
	"time"
)

// LogEntry represents a parsed log line with its timestamp
type LogEntry struct {
	Timestamp time.Time
	Raw       string
	HasTime   bool
}

// Standard timestamp pattern: MM/DD/YYYY HH:MM:SS AM/PM
// Example: 01/29/2026 01:05:24 AM
var timestampRegex = regexp.MustCompile(`(\d{2}/\d{2}/\d{4}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)`)

// ParseTimestamp extracts and parses a timestamp from a log line
func ParseTimestamp(line string) (time.Time, bool) {
	match := timestampRegex.FindStringSubmatch(line)
	if len(match) < 2 {
		return time.Time{}, false
	}

	// Parse: 01/29/2026 01:05:24 AM
	t, err := time.Parse("01/02/2006 03:04:05 PM", match[1])
	if err != nil {
		return time.Time{}, false
	}
	return t, true
}

// ParseLogs reads log lines from a reader and returns parsed entries
func ParseLogs(r io.Reader) ([]LogEntry, error) {
	var entries []LogEntry
	scanner := bufio.NewScanner(r)

	// Increase buffer size for long lines
	buf := make([]byte, 0, 64*1024)
	scanner.Buffer(buf, 1024*1024)

	for scanner.Scan() {
		line := scanner.Text()
		if strings.TrimSpace(line) == "" {
			continue
		}

		ts, hasTime := ParseTimestamp(line)
		entries = append(entries, LogEntry{
			Timestamp: ts,
			Raw:       line,
			HasTime:   hasTime,
		})
	}

	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("error reading input: %w", err)
	}

	return entries, nil
}

// SortChronologically sorts log entries by timestamp
// Entries without timestamps are placed at the end
func SortChronologically(entries []LogEntry) {
	sort.SliceStable(entries, func(i, j int) bool {
		// Entries without timestamps go to the end
		if !entries[i].HasTime && !entries[j].HasTime {
			return false
		}
		if !entries[i].HasTime {
			return false
		}
		if !entries[j].HasTime {
			return true
		}
		return entries[i].Timestamp.Before(entries[j].Timestamp)
	})
}

// DisplayInPager writes the sorted logs to a pager (less)
func DisplayInPager(entries []LogEntry) error {
	// Check if stdout is a terminal
	if fileInfo, _ := os.Stdout.Stat(); (fileInfo.Mode() & os.ModeCharDevice) == 0 {
		// Not a terminal, just print to stdout
		for _, entry := range entries {
			fmt.Println(entry.Raw)
		}
		return nil
	}

	// Find pager: prefer less, fall back to more
	pager := findPager()
	if pager == "" {
		// No pager found, just print
		for _, entry := range entries {
			fmt.Println(entry.Raw)
		}
		return nil
	}

	// Build pager command with useful flags for less
	var cmd *exec.Cmd
	if strings.Contains(pager, "less") {
		// -R: interpret ANSI color codes
		// -S: chop long lines (don't wrap)
		// -X: don't clear screen on exit
		// -F: quit if entire file fits on screen
		cmd = exec.Command(pager, "-RSXF")
	} else {
		cmd = exec.Command(pager)
	}

	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	stdin, err := cmd.StdinPipe()
	if err != nil {
		return fmt.Errorf("failed to create stdin pipe: %w", err)
	}

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("failed to start pager: %w", err)
	}

	// Write entries to pager
	for _, entry := range entries {
		if _, err := fmt.Fprintln(stdin, entry.Raw); err != nil {
			// Broken pipe is expected if user quits pager early
			break
		}
	}
	_ = stdin.Close()

	// Wait for pager to exit (ignore broken pipe errors)
	_ = cmd.Wait()
	return nil
}

// findPager looks for available pager programs
func findPager() string {
	// Check PAGER environment variable first
	if pager := os.Getenv("PAGER"); pager != "" {
		return pager
	}

	// Try common pagers
	pagers := []string{"less", "more"}
	for _, p := range pagers {
		if path, err := exec.LookPath(p); err == nil {
			return path
		}
	}

	return ""
}

// ProcessAndDisplay is the main entry point - reads, parses, sorts, and displays logs
func ProcessAndDisplay(r io.Reader) error {
	entries, err := ParseLogs(r)
	if err != nil {
		return err
	}

	if len(entries) == 0 {
		return fmt.Errorf("no log entries found in input")
	}

	SortChronologically(entries)
	return DisplayInPager(entries)
}
