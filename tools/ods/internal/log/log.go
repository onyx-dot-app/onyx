// Package log provides printf-style logging on top of the standard library
// log/slog package. Output goes to stderr as "LEVEL message", with color when
// stderr is a terminal.
package log

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"os"
	"strings"
	"sync"
)

// Levels mirror the slog levels so callers do not need to import log/slog.
const (
	LevelDebug = slog.LevelDebug
	LevelInfo  = slog.LevelInfo
	LevelWarn  = slog.LevelWarn
	LevelError = slog.LevelError
)

var (
	level  = new(slog.LevelVar)
	logger = slog.New(newHandler(os.Stderr, level))
)

// SetLevel sets the minimum level to log.
func SetLevel(l slog.Level) {
	level.Set(l)
}

// Enabled reports whether messages at the given level are logged.
func Enabled(l slog.Level) bool {
	return logger.Enabled(context.Background(), l)
}

func Debugf(format string, args ...any) { output(LevelDebug, fmt.Sprintf(format, args...)) }
func Info(args ...any)                  { output(LevelInfo, fmt.Sprint(args...)) }
func Infof(format string, args ...any)  { output(LevelInfo, fmt.Sprintf(format, args...)) }
func Warn(args ...any)                  { output(LevelWarn, fmt.Sprint(args...)) }
func Warnf(format string, args ...any)  { output(LevelWarn, fmt.Sprintf(format, args...)) }
func Error(args ...any)                 { output(LevelError, fmt.Sprint(args...)) }
func Errorf(format string, args ...any) { output(LevelError, fmt.Sprintf(format, args...)) }

// Fatal logs at error level and exits with status 1.
func Fatal(args ...any) {
	output(LevelError, fmt.Sprint(args...))
	os.Exit(1)
}

// Fatalf logs at error level and exits with status 1.
func Fatalf(format string, args ...any) {
	output(LevelError, fmt.Sprintf(format, args...))
	os.Exit(1)
}

func output(l slog.Level, msg string) {
	logger.Log(context.Background(), l, msg)
}

// handler renders records as "LEVEL message" without a timestamp. Attributes
// are appended as key=value pairs.
type handler struct {
	mu    *sync.Mutex
	out   io.Writer
	level slog.Leveler
	color bool
	attrs []slog.Attr
}

func newHandler(out *os.File, level slog.Leveler) *handler {
	return &handler{mu: &sync.Mutex{}, out: out, level: level, color: isTerminal(out)}
}

func isTerminal(f *os.File) bool {
	info, err := f.Stat()
	return err == nil && info.Mode()&os.ModeCharDevice != 0
}

func (h *handler) Enabled(_ context.Context, l slog.Level) bool {
	return l >= h.level.Level()
}

func (h *handler) Handle(_ context.Context, r slog.Record) error {
	var b strings.Builder
	b.WriteString(h.label(r.Level))
	b.WriteByte(' ')
	b.WriteString(r.Message)
	for _, a := range h.attrs {
		writeAttr(&b, a)
	}
	r.Attrs(func(a slog.Attr) bool {
		writeAttr(&b, a)
		return true
	})
	b.WriteByte('\n')

	h.mu.Lock()
	defer h.mu.Unlock()
	_, err := io.WriteString(h.out, b.String())
	return err
}

func (h *handler) WithAttrs(attrs []slog.Attr) slog.Handler {
	next := *h
	next.attrs = append(append([]slog.Attr{}, h.attrs...), attrs...)
	return &next
}

// WithGroup is unused; groups are ignored.
func (h *handler) WithGroup(string) slog.Handler { return h }

func (h *handler) label(l slog.Level) string {
	name := map[slog.Level]string{
		LevelDebug: "DEBUG",
		LevelInfo:  "INFO ",
		LevelWarn:  "WARN ",
		LevelError: "ERROR",
	}[l]
	if name == "" {
		name = l.String()
	}
	if !h.color {
		return name
	}
	code := map[slog.Level]string{
		LevelDebug: "37",
		LevelInfo:  "36",
		LevelWarn:  "33",
		LevelError: "31",
	}[l]
	if code == "" {
		return name
	}
	return "\x1b[" + code + "m" + name + "\x1b[0m"
}

func writeAttr(b *strings.Builder, a slog.Attr) {
	fmt.Fprintf(b, " %s=%v", a.Key, a.Value.Any())
}
