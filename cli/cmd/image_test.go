package cmd

import (
	"bytes"
	"encoding/base64"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/spf13/cobra"
)

func testIOStreams() *iostreams.IOStreams {
	return &iostreams.IOStreams{
		In:          &bytes.Buffer{},
		Out:         &bytes.Buffer{},
		ErrOut:      &bytes.Buffer{},
		IsStdinTTY:  false,
		IsStdoutTTY: false,
	}
}

func assertExitCode(t *testing.T, err error, want exitcodes.Code) {
	t.Helper()
	if err == nil {
		t.Fatalf("expected error with exit code %d, got nil", want)
	}
	var exitErr *exitcodes.ExitError
	if !errors.As(err, &exitErr) {
		t.Fatalf("expected *exitcodes.ExitError, got %T: %v", err, err)
	}
	if exitErr.Code != want {
		t.Fatalf("expected exit code %d, got %d (%v)", want, exitErr.Code, err)
	}
}

func TestBuildImageRequest_ForwardsFields(t *testing.T) {
	refs := []models.ImageReferencePayload{{DataBase64: "x", MimeType: "image/png"}}
	req := buildImageRequest(
		imageOptions{prompt: "a cat", shape: "landscape", quality: "high", num: 3},
		refs,
	)
	if req.Prompt != "a cat" || req.Shape != "landscape" || req.Quality != "high" || req.N != 3 {
		t.Fatalf("fields not forwarded: %+v", req)
	}
	if len(req.ReferenceImages) != 1 || req.ReferenceImages[0].DataBase64 != "x" {
		t.Fatalf("reference images not forwarded: %+v", req.ReferenceImages)
	}
}

func TestRunImageGeneration_EmptyPrompt(t *testing.T) {
	err := runImageGeneration(&cobra.Command{}, testIOStreams(),
		imageOptions{prompt: "  ", shape: "square", num: 1, output: "out.png"})
	assertExitCode(t, err, exitcodes.BadRequest)
}

func TestRunImageGeneration_InvalidShape(t *testing.T) {
	err := runImageGeneration(&cobra.Command{}, testIOStreams(),
		imageOptions{prompt: "a cat", shape: "diagonal", num: 1, output: "out.png"})
	assertExitCode(t, err, exitcodes.BadRequest)
}

func TestRunImageGeneration_NumTooLow(t *testing.T) {
	err := runImageGeneration(&cobra.Command{}, testIOStreams(),
		imageOptions{prompt: "a cat", shape: "square", num: 0, output: "out.png"})
	assertExitCode(t, err, exitcodes.BadRequest)
}

func TestWriteGeneratedImages_Single(t *testing.T) {
	dir := t.TempDir()
	out := filepath.Join(dir, "art.png")
	raw := []byte("\x89PNG\r\n")
	images := []models.GeneratedImagePayload{
		{DataBase64: base64.StdEncoding.EncodeToString(raw), MimeType: "image/png"},
	}

	paths, err := writeGeneratedImages(images, out)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(paths) != 1 || paths[0] != out {
		t.Fatalf("expected [%s], got %v", out, paths)
	}
	got, err := os.ReadFile(out)
	if err != nil {
		t.Fatalf("reading output: %v", err)
	}
	if !bytes.Equal(got, raw) {
		t.Fatalf("written bytes mismatch: %q", got)
	}
}

func TestWriteGeneratedImages_MultipleSuffixes(t *testing.T) {
	dir := t.TempDir()
	out := filepath.Join(dir, "art.png")
	b64 := base64.StdEncoding.EncodeToString([]byte("data"))
	images := []models.GeneratedImagePayload{
		{DataBase64: b64}, {DataBase64: b64},
	}

	paths, err := writeGeneratedImages(images, out)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := []string{
		filepath.Join(dir, "art_1.png"),
		filepath.Join(dir, "art_2.png"),
	}
	if len(paths) != 2 || paths[0] != want[0] || paths[1] != want[1] {
		t.Fatalf("expected %v, got %v", want, paths)
	}
	for _, p := range want {
		if _, err := os.Stat(p); err != nil {
			t.Fatalf("expected file %s: %v", p, err)
		}
	}
}

func TestWriteGeneratedImages_FailsIfExists(t *testing.T) {
	dir := t.TempDir()
	out := filepath.Join(dir, "art.png")
	if err := os.WriteFile(out, []byte("existing"), 0o644); err != nil {
		t.Fatalf("setup: %v", err)
	}
	images := []models.GeneratedImagePayload{
		{DataBase64: base64.StdEncoding.EncodeToString([]byte("new"))},
	}

	_, err := writeGeneratedImages(images, out)
	if err == nil {
		t.Fatal("expected error when output already exists")
	}
	got, _ := os.ReadFile(out)
	if string(got) != "existing" {
		t.Fatalf("existing file was modified: %q", got)
	}
}

func TestWriteGeneratedImages_CreatesParentDirs(t *testing.T) {
	dir := t.TempDir()
	out := filepath.Join(dir, "outputs", "images", "art.png")
	images := []models.GeneratedImagePayload{
		{DataBase64: base64.StdEncoding.EncodeToString([]byte("data"))},
	}

	paths, err := writeGeneratedImages(images, out)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(paths) != 1 || paths[0] != out {
		t.Fatalf("expected [%s], got %v", out, paths)
	}
	if _, err := os.Stat(out); err != nil {
		t.Fatalf("expected file at nested path: %v", err)
	}
}

func TestWriteGeneratedImages_Empty(t *testing.T) {
	_, err := writeGeneratedImages(nil, "out.png")
	assertExitCode(t, err, exitcodes.ServerError)
}

func TestWriteGeneratedImages_BadBase64(t *testing.T) {
	dir := t.TempDir()
	images := []models.GeneratedImagePayload{{DataBase64: "not!valid!"}}
	_, err := writeGeneratedImages(images, filepath.Join(dir, "out.png"))
	assertExitCode(t, err, exitcodes.ServerError)
}

func TestLoadReferenceImages_ReadsAndEncodes(t *testing.T) {
	dir := t.TempDir()
	jpg := filepath.Join(dir, "ref.jpg")
	raw := []byte("\xff\xd8jpegdata")
	if err := os.WriteFile(jpg, raw, 0o644); err != nil {
		t.Fatalf("setup: %v", err)
	}

	refs, err := loadReferenceImages([]string{jpg})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(refs) != 1 {
		t.Fatalf("expected 1 reference, got %d", len(refs))
	}
	if refs[0].MimeType != "image/jpeg" {
		t.Fatalf("expected image/jpeg, got %s", refs[0].MimeType)
	}
	if refs[0].DataBase64 != base64.StdEncoding.EncodeToString(raw) {
		t.Fatalf("base64 mismatch")
	}
}

func TestLoadReferenceImages_UnknownExtDefaultsPng(t *testing.T) {
	dir := t.TempDir()
	f := filepath.Join(dir, "ref.bin")
	if err := os.WriteFile(f, []byte("x"), 0o644); err != nil {
		t.Fatalf("setup: %v", err)
	}
	refs, err := loadReferenceImages([]string{f})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if refs[0].MimeType != "image/png" {
		t.Fatalf("expected image/png default, got %s", refs[0].MimeType)
	}
}

func TestLoadReferenceImages_MissingFile(t *testing.T) {
	_, err := loadReferenceImages([]string{"/does/not/exist.png"})
	assertExitCode(t, err, exitcodes.BadRequest)
}

func TestLoadReferenceImages_Empty(t *testing.T) {
	refs, err := loadReferenceImages(nil)
	if err != nil || refs != nil {
		t.Fatalf("expected (nil, nil), got (%v, %v)", refs, err)
	}
}

func TestImageErrorToExit_NotConfigured(t *testing.T) {
	err := imageErrorToExit(&api.OnyxAPIError{StatusCode: 404, Detail: "no config"})
	assertExitCode(t, err, exitcodes.NotAvailable)
}

func TestImageErrorToExit_ServerError(t *testing.T) {
	err := imageErrorToExit(&api.OnyxAPIError{StatusCode: 500, Detail: "boom"})
	assertExitCode(t, err, exitcodes.ServerError)
}
