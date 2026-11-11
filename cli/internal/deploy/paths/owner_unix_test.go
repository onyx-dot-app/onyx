//go:build !windows

package paths

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestResolveRefusesUntrustedLegacyInstall(t *testing.T) {
	cases := []struct {
		name    string
		setup   func(t *testing.T, legacy string)
		wantErr string
	}{
		{
			name: "writable by other users",
			setup: func(t *testing.T, legacy string) {
				if err := os.Chmod(filepath.Join(legacy, "deployment"), 0o777); err != nil {
					t.Fatal(err)
				}
			},
			wantErr: "is writable by its group or other users",
		},
		{
			name: "writable by its group",
			setup: func(t *testing.T, legacy string) {
				if err := os.Chmod(legacy, 0o775); err != nil {
					t.Fatal(err)
				}
			},
			wantErr: "is writable by its group or other users",
		},
		{
			name: "owned by another user",
			setup: func(t *testing.T, _ string) {
				uid := os.Getuid()
				currentUID = func() int { return uid + 1 }
				t.Cleanup(func() { currentUID = os.Getuid })
			},
			wantErr: "is owned by another user",
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			cwd, _ := isolate(t)
			legacy := filepath.Join(cwd, "onyx_data")
			markInstall(t, legacy)
			c.setup(t, legacy)

			_, err := Resolve("")

			if err == nil || !strings.Contains(err.Error(), c.wantErr) || !strings.Contains(err.Error(), "--dir onyx_data") {
				t.Fatalf("expected an error containing %q and the --dir hint, got %v", c.wantErr, err)
			}
		})
	}
}
