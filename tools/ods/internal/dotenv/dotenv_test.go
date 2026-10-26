package dotenv

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestLoadAndUpsert(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".env")
	content := "# comment\n\nexport A=1\nB=\"two words\"\nC='x'\nD=plain # not stripped\n"
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	got, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"A=1", "B=two words", "C=x", "D=plain # not stripped"}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("Load = %v, want %v", got, want)
	}

	if err := Upsert(path, map[string]string{"B": "3", "E": "new"}); err != nil {
		t.Fatal(err)
	}
	data, _ := os.ReadFile(path)
	if string(data) != "# comment\n\nexport A=1\nB=3\nC='x'\nD=plain # not stripped\nE=new\n" {
		t.Errorf("after upsert:\n%s", data)
	}

	missing := filepath.Join(t.TempDir(), "new.env")
	if err := Upsert(missing, map[string]string{"K": "v"}); err != nil {
		t.Fatal(err)
	}
	data, _ = os.ReadFile(missing)
	if string(data) != "K=v\n" {
		t.Errorf("new file: %q", data)
	}
	if _, err := Load(filepath.Join(t.TempDir(), "none")); err == nil {
		t.Error("missing file did not error")
	}
}
