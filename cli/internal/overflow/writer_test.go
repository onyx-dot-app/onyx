package overflow

import (
	"os"
	"testing"
)

func TestWriter_NoLimit(t *testing.T) {
	w := &Writer{Limit: 0}
	w.Write("hello world")
	if w.truncated {
		t.Fatal("should not be truncated with limit 0")
	}
	if w.totalBytes != 11 {
		t.Fatalf("expected 11 total bytes, got %d", w.totalBytes)
	}
}

func TestWriter_UnderLimit(t *testing.T) {
	w := &Writer{Limit: 100}
	w.Write("hello")
	w.Write(" world")
	if w.truncated {
		t.Fatal("should not be truncated when under limit")
	}
	if w.written != 11 {
		t.Fatalf("expected 11 written bytes, got %d", w.written)
	}
}

func TestWriter_OverLimit(t *testing.T) {
	w := &Writer{Limit: 5}
	w.Write("hello world") // 11 bytes, limit 5
	if !w.truncated {
		t.Fatal("should be truncated")
	}
	if w.written != 5 {
		t.Fatalf("expected 5 written bytes, got %d", w.written)
	}
	if w.totalBytes != 11 {
		t.Fatalf("expected 11 total bytes, got %d", w.totalBytes)
	}
	if w.tmpFile == nil {
		t.Fatal("temp file should have been created")
	}
	_ = w.tmpFile.Close()
	data, _ := os.ReadFile(w.tmpFile.Name())
	_ = os.Remove(w.tmpFile.Name())
	if string(data) != "hello world" {
		t.Fatalf("temp file should contain full content, got %q", string(data))
	}
}

func TestWriter_MultipleChunks(t *testing.T) {
	w := &Writer{Limit: 10}
	w.Write("hello") // 5 bytes
	w.Write(" ")     // 6 bytes
	w.Write("world") // 11 bytes, crosses limit
	w.Write("!")     // 12 bytes, already truncated

	if !w.truncated {
		t.Fatal("should be truncated")
	}
	if w.written != 10 {
		t.Fatalf("expected 10 written bytes, got %d", w.written)
	}
	if w.totalBytes != 12 {
		t.Fatalf("expected 12 total bytes, got %d", w.totalBytes)
	}
	if w.tmpFile == nil {
		t.Fatal("temp file should have been created")
	}
	_ = w.tmpFile.Close()
	data, _ := os.ReadFile(w.tmpFile.Name())
	_ = os.Remove(w.tmpFile.Name())
	if string(data) != "hello world!" {
		t.Fatalf("temp file should contain full content, got %q", string(data))
	}
}

func TestWriter_QuietMode(t *testing.T) {
	w := &Writer{Limit: 0, Quiet: true}
	w.Write("hello")
	w.Write(" world")

	if w.written != 0 {
		t.Fatalf("quiet mode should not write to stdout, got %d written", w.written)
	}
	if w.totalBytes != 11 {
		t.Fatalf("expected 11 total bytes, got %d", w.totalBytes)
	}
	if w.buf.String() != "hello world" {
		t.Fatalf("buffer should contain full content, got %q", w.buf.String())
	}
}
