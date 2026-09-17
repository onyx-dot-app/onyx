package cmd

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"
	"time"
)

func writeFile(t *testing.T, path string, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func setMtime(t *testing.T, path string, mtime time.Time) {
	t.Helper()
	if err := os.Chtimes(path, mtime, mtime); err != nil {
		t.Fatal(err)
	}
}

func TestNodeModulesNeedsInstall(t *testing.T) {
	now := time.Now()

	t.Run("missing node_modules", func(t *testing.T) {
		webDir := t.TempDir()
		needs, reason := nodeModulesNeedsInstall(webDir)
		if !needs {
			t.Fatal("expected install for missing node_modules")
		}
		if reason != "node_modules not found" {
			t.Fatalf("unexpected reason: %q", reason)
		}
	})

	t.Run("empty node_modules", func(t *testing.T) {
		webDir := t.TempDir()
		if err := os.Mkdir(filepath.Join(webDir, "node_modules"), 0o755); err != nil {
			t.Fatal(err)
		}
		needs, reason := nodeModulesNeedsInstall(webDir)
		if !needs {
			t.Fatal("expected install for empty node_modules")
		}
		if reason != "node_modules is empty" {
			t.Fatalf("unexpected reason: %q", reason)
		}
	})

	t.Run("populated without stamp is stale", func(t *testing.T) {
		webDir := t.TempDir()
		writeFile(t, filepath.Join(webDir, "bun.lock"), "lock-v1")
		writeFile(t, filepath.Join(webDir, "node_modules", "pkg", "index.js"), "")
		needs, _ := nodeModulesNeedsInstall(webDir)
		if !needs {
			t.Fatal("expected install when no stamp recorded")
		}
	})

	t.Run("stamp matches lockfile", func(t *testing.T) {
		webDir := t.TempDir()
		writeFile(t, filepath.Join(webDir, "bun.lock"), "lock-v1")
		writeFile(t, filepath.Join(webDir, "node_modules", "pkg", "index.js"), "")
		writeLockStamp(webDir)
		needs, reason := nodeModulesNeedsInstall(webDir)
		if needs {
			t.Fatalf("expected no install with matching stamp, got: %q", reason)
		}
	})

	t.Run("lockfile changed after stamp", func(t *testing.T) {
		webDir := t.TempDir()
		writeFile(t, filepath.Join(webDir, "bun.lock"), "lock-v1")
		writeFile(t, filepath.Join(webDir, "node_modules", "pkg", "index.js"), "")
		writeLockStamp(webDir)
		writeFile(t, filepath.Join(webDir, "bun.lock"), "lock-v2")
		setMtime(t, filepath.Join(webDir, "bun.lock"), now)
		needs, _ := nodeModulesNeedsInstall(webDir)
		if !needs {
			t.Fatal("expected install after lockfile change")
		}
	})

	t.Run("stamp replaces an existing file it cannot write in place", func(t *testing.T) {
		// Sessions run as different users against the shared node_modules
		// volume, so the previous stamp may not be writable — only
		// replaceable via the directory. Simulate with a read-only stamp.
		webDir := t.TempDir()
		writeFile(t, filepath.Join(webDir, "bun.lock"), "lock-v2")
		writeFile(t, filepath.Join(webDir, "node_modules", "pkg", "index.js"), "")
		stampPath := filepath.Join(webDir, "node_modules", lockStampName)
		writeFile(t, stampPath, "stale-hash")
		if err := os.Chmod(stampPath, 0o444); err != nil {
			t.Fatal(err)
		}
		writeLockStamp(webDir)
		needs, reason := nodeModulesNeedsInstall(webDir)
		if needs {
			t.Fatalf("expected stamp to be replaced despite read-only file, got: %q", reason)
		}
	})

	t.Run("no lockfile skips staleness check", func(t *testing.T) {
		webDir := t.TempDir()
		writeFile(t, filepath.Join(webDir, "node_modules", "pkg", "index.js"), "")
		needs, _ := nodeModulesNeedsInstall(webDir)
		if needs {
			t.Fatal("expected no install without a lockfile to compare")
		}
	})
}

func TestLibNeedsBuild(t *testing.T) {
	old := time.Now().Add(-time.Hour)
	older := old.Add(-time.Hour)

	t.Run("missing package is skipped", func(t *testing.T) {
		needs, _ := libNeedsBuild(filepath.Join(t.TempDir(), "lib", "nope"))
		if needs {
			t.Fatal("expected missing package to be skipped")
		}
	})

	t.Run("missing dist", func(t *testing.T) {
		pkgDir := t.TempDir()
		writeFile(t, filepath.Join(pkgDir, "src", "index.ts"), "")
		needs, reason := libNeedsBuild(pkgDir)
		if !needs {
			t.Fatal("expected build for missing dist")
		}
		if reason != "has no dist build" {
			t.Fatalf("unexpected reason: %q", reason)
		}
	})

	t.Run("dist newer than sources", func(t *testing.T) {
		pkgDir := t.TempDir()
		src := filepath.Join(pkgDir, "src", "index.ts")
		dist := filepath.Join(pkgDir, "dist", "index.js")
		writeFile(t, src, "")
		writeFile(t, dist, "")
		setMtime(t, src, older)
		setMtime(t, filepath.Join(pkgDir, "src"), older)
		setMtime(t, pkgDir, older)
		needs, reason := libNeedsBuild(pkgDir)
		if needs {
			t.Fatalf("expected no build when dist is fresh, got: %q", reason)
		}
	})

	t.Run("source newer than dist", func(t *testing.T) {
		pkgDir := t.TempDir()
		src := filepath.Join(pkgDir, "src", "index.ts")
		dist := filepath.Join(pkgDir, "dist", "index.js")
		writeFile(t, src, "")
		writeFile(t, dist, "")
		setMtime(t, dist, older)
		setMtime(t, filepath.Join(pkgDir, "dist"), older)
		setMtime(t, src, old)
		needs, _ := libNeedsBuild(pkgDir)
		if !needs {
			t.Fatal("expected build when a source is newer than dist")
		}
	})

	t.Run("changes under excluded dirs are ignored", func(t *testing.T) {
		pkgDir := t.TempDir()
		src := filepath.Join(pkgDir, "src", "index.ts")
		dist := filepath.Join(pkgDir, "dist", "index.js")
		dep := filepath.Join(pkgDir, "node_modules", "dep", "index.js")
		writeFile(t, src, "")
		writeFile(t, dist, "")
		writeFile(t, dep, "")
		setMtime(t, src, older)
		setMtime(t, filepath.Join(pkgDir, "src"), older)
		setMtime(t, pkgDir, older)
		needs, reason := libNeedsBuild(pkgDir)
		if needs {
			t.Fatalf("expected node_modules churn to be ignored, got: %q", reason)
		}
	})
}

// devtoolFreshWebDir builds a repository whose web directory needs neither an
// install nor a library build, and returns the web dir and a fake bun's call log.
func devtoolFreshWebDir(t *testing.T) (string, string) {
	t.Helper()
	binDir := devtoolBinDir(t)
	webDir := filepath.Join(devtoolRepo(t), "web")
	writeFile(t, filepath.Join(webDir, "bun.lock"), "lock-v1")
	writeFile(t, filepath.Join(webDir, "node_modules", "pkg", "index.js"), "")
	writeLockStamp(webDir)
	return webDir, devtoolFakeTool(t, binDir, "bun", "")
}

func TestRunWebScript_forwardsScriptArgs(t *testing.T) {
	cases := []struct {
		name string
		args []string
		want []string
	}{
		{"script only", []string{"dev"}, []string{"run", "dev"}},
		{"flags get a separator", []string{"test", "--watch"}, []string{"run", "test", "--", "--watch"}},
		{"separator is not repeated", []string{"test", "--", "--watch"}, []string{"run", "test", "--", "--watch"}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			webDir, bunCalls := devtoolFreshWebDir(t)

			runWebScript(c.args)

			want := []devtoolCall{{Dir: webDir, Args: c.want}}
			if got := devtoolCalls(t, bunCalls); !reflect.DeepEqual(got, want) {
				t.Fatalf("expected %q, got %q", want, got)
			}
		})
	}
}

func TestPrepareWebDir_installsAndBuildsLibsInOrder(t *testing.T) {
	binDir := devtoolBinDir(t)
	webDir := filepath.Join(devtoolRepo(t), "web")
	writeFile(t, filepath.Join(webDir, "bun.lock"), "lock-v1")
	if err := os.MkdirAll(filepath.Join(webDir, "node_modules"), 0o755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(webDir, "lib", "opal", "src", "index.ts"), "")
	writeFile(t, filepath.Join(webDir, "lib", "shared", "src", "index.ts"), "")
	bunCalls := devtoolFakeTool(t, binDir, "bun", "")

	prepareWebDir(webDir)

	want := []devtoolCall{
		{Dir: webDir, Args: []string{"install", "--frozen-lockfile"}},
		{Dir: filepath.Join(webDir, "lib", "shared"), Args: []string{"run", "build"}},
		{Dir: filepath.Join(webDir, "lib", "opal"), Args: []string{"run", "build"}},
	}
	if got := devtoolCalls(t, bunCalls); !reflect.DeepEqual(got, want) {
		t.Fatalf("expected %q, got %q", want, got)
	}
	sum := sha256.Sum256([]byte("lock-v1"))
	stamp, err := os.ReadFile(filepath.Join(webDir, "node_modules", lockStampName))
	if err != nil {
		t.Fatalf("expected a lock stamp after install: %v", err)
	}
	if got, want := string(stamp), hex.EncodeToString(sum[:])+"\n"; got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestPrepareWebDir_skipsFreshInstallAndLibs(t *testing.T) {
	webDir, bunCalls := devtoolFreshWebDir(t)
	older := time.Now().Add(-time.Hour)
	for _, lib := range webLibPackages {
		pkgDir := filepath.Join(webDir, lib)
		src := filepath.Join(pkgDir, "src", "index.ts")
		writeFile(t, src, "")
		writeFile(t, filepath.Join(pkgDir, "dist", "index.js"), "")
		for _, path := range []string{src, filepath.Dir(src), pkgDir} {
			setMtime(t, path, older)
		}
	}

	prepareWebDir(webDir)

	if got := devtoolCalls(t, bunCalls); got != nil {
		t.Fatalf("expected no bun calls, got %q", got)
	}
}

func TestLoadScripts_readsPackageJSON(t *testing.T) {
	loaders := []struct {
		dir   string
		load  func() (map[string]string, error)
		names func() []string
	}{
		{"web", loadWebScripts, webScriptNames},
		{"desktop", loadDesktopScripts, desktopScriptNames},
	}
	for _, l := range loaders {
		t.Run(l.dir, func(t *testing.T) {
			packageJSON := filepath.Join(devtoolRepo(t), l.dir, "package.json")

			if _, err := l.load(); err == nil || !strings.Contains(err.Error(), "failed to read") {
				t.Fatalf("expected a read error without package.json, got %v", err)
			}

			writeFile(t, packageJSON, "{")
			if _, err := l.load(); err == nil || !strings.Contains(err.Error(), "failed to parse") {
				t.Fatalf("expected a parse error, got %v", err)
			}
			if got := l.names(); got != nil {
				t.Fatalf("expected no names for an unparseable package.json, got %q", got)
			}

			writeFile(t, packageJSON, `{"name": "x"}`)
			if scripts, err := l.load(); err != nil || scripts != nil {
				t.Fatalf("expected no scripts and no error, got %v, %v", scripts, err)
			}

			writeFile(t, packageJSON, `{"scripts": {"lint": "eslint", "dev": "next dev"}}`)
			if got, want := l.names(), []string{"dev", "lint"}; !slices.Equal(got, want) {
				t.Fatalf("expected %q, got %q", want, got)
			}
		})
	}

	t.Run("outside a repository", func(t *testing.T) {
		t.Chdir(t.TempDir())
		if _, err := loadWebScripts(); err == nil {
			t.Fatal("expected an error outside a repository")
		}
		if _, err := loadDesktopScripts(); err == nil {
			t.Fatal("expected an error outside a repository")
		}
	})
}
