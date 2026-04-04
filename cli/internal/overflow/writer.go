// Package overflow provides a streaming writer that auto-truncates output
// for non-TTY callers (e.g., AI agents, scripts). Full content is saved to
// a temp file on disk; only the first N bytes are printed to stdout.
package overflow

import (
	"fmt"
	"os"
	"strings"

	log "github.com/sirupsen/logrus"
)

// Writer handles streaming output with optional truncation.
// When Limit > 0, it streams to a temp file on disk (not memory) and stops
// writing to stdout after Limit bytes. When Limit == 0, it writes directly
// to stdout. In Quiet mode, it buffers in memory and prints once at the end.
type Writer struct {
	Limit      int
	Quiet      bool
	written    int
	totalBytes int
	truncated  bool
	buf        strings.Builder // used only in quiet mode
	tmpFile    *os.File        // used only in truncation mode (Limit > 0)
}

// Write sends a chunk of content through the writer.
func (w *Writer) Write(s string) {
	w.totalBytes += len(s)

	// Quiet mode: buffer in memory, print nothing
	if w.Quiet {
		w.buf.WriteString(s)
		return
	}

	if w.Limit <= 0 {
		fmt.Print(s)
		return
	}

	// Truncation mode: stream all content to temp file on disk
	if w.tmpFile == nil {
		f, err := os.CreateTemp("", "onyx-ask-*.txt")
		if err != nil {
			// Fall back to no-truncation if we can't create the file
			fmt.Fprintf(os.Stderr, "warning: could not create temp file: %v\n", err)
			w.Limit = 0
			fmt.Print(s)
			return
		}
		w.tmpFile = f
	}
	if _, err := w.tmpFile.WriteString(s); err != nil {
		// Disk write failed — abandon truncation, stream directly to stdout
		fmt.Fprintf(os.Stderr, "warning: temp file write failed: %v\n", err)
		w.closeTmpFile(true)
		w.Limit = 0
		w.truncated = false
		fmt.Print(s)
		return
	}

	if w.truncated {
		return
	}

	remaining := w.Limit - w.written
	if len(s) <= remaining {
		fmt.Print(s)
		w.written += len(s)
	} else {
		if remaining > 0 {
			fmt.Print(s[:remaining])
			w.written += remaining
		}
		w.truncated = true
	}
}

// Finish flushes remaining output. Call once after all Write calls are done.
func (w *Writer) Finish() {
	// Quiet mode: print buffered content at once
	if w.Quiet {
		fmt.Println(w.buf.String())
		return
	}

	if !w.truncated {
		w.closeTmpFile(true) // clean up unused temp file
		fmt.Println()
		return
	}

	// Close the temp file so it's readable
	tmpPath := w.tmpFile.Name()
	w.closeTmpFile(false) // close but keep the file

	fmt.Printf("\n\n--- response truncated (%d bytes total) ---\n", w.totalBytes)
	fmt.Printf("Full response: %s\n", tmpPath)
	fmt.Printf("Explore:\n")
	fmt.Printf("  cat %s | grep \"<pattern>\"\n", tmpPath)
	fmt.Printf("  cat %s | tail -50\n", tmpPath)
}

// closeTmpFile closes and optionally removes the temp file.
func (w *Writer) closeTmpFile(remove bool) {
	if w.tmpFile == nil {
		return
	}
	if err := w.tmpFile.Close(); err != nil {
		log.Debugf("warning: failed to close temp file: %v", err)
	}
	if remove {
		if err := os.Remove(w.tmpFile.Name()); err != nil {
			log.Debugf("warning: failed to remove temp file: %v", err)
		}
	}
	w.tmpFile = nil
}
