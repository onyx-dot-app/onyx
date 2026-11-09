package journal

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

const id1 = "11111111-1111-4111-8111-111111111111"

func TestWriteLoadRemove(t *testing.T) {
	j := &Journal{Dir: t.TempDir()}
	r := Record{SandboxID: id1, Attempt: 3, Generation: 42, State: Running, PID: 1234, PIDStart: 99, UID: 1000001,
		Chroot: "/d/jail/firecracker/" + id1, Template: "t1", VCPUs: 2, MemMiB: 4096, ScratchGiB: 2,
		StartedAt: time.Unix(1700000000, 0).UTC()}
	if err := j.Write(r); err != nil {
		t.Fatal(err)
	}
	r.Attempt = 4
	if err := j.Write(r); err != nil {
		t.Fatal(err)
	}
	recs, bad, err := j.Load()
	if err != nil || len(bad) != 0 || len(recs) != 1 {
		t.Fatalf("load: %v %v %v", recs, bad, err)
	}
	if recs[0] != r {
		t.Fatalf("round trip\n got %+v\nwant %+v", recs[0], r)
	}
	if err := j.Remove(id1); err != nil {
		t.Fatal(err)
	}
	if err := j.Remove(id1); err != nil {
		t.Fatalf("second remove: %v", err)
	}
	if recs, _, _ := j.Load(); len(recs) != 0 {
		t.Fatalf("record survived remove: %v", recs)
	}
	if err := j.Write(Record{SandboxID: "../x", State: Running}); err == nil {
		t.Fatal("wrote a record with a bad sandbox id")
	}
}

// TestCrashBeforeRename simulates a crash after the temporary file was
// written and before the rename: the old record must stay intact.
func TestCrashBeforeRename(t *testing.T) {
	dir := t.TempDir()
	j := &Journal{Dir: dir}
	old := Record{SandboxID: id1, Attempt: 1, Generation: 7, State: Running, PID: 10}
	if err := j.Write(old); err != nil {
		t.Fatal(err)
	}
	tmp := filepath.Join(dir, "."+id1+".123456.tmp")
	if err := os.WriteFile(tmp, []byte(`{"sandbox_id":"`+id1+`","attempt":2,"sta`), 0o600); err != nil {
		t.Fatal(err)
	}
	recs, bad, err := j.Load()
	if err != nil || len(bad) != 0 || len(recs) != 1 || recs[0] != old {
		t.Fatalf("after crash: %v %v %v", recs, bad, err)
	}
	if _, err := os.Stat(tmp); !os.IsNotExist(err) {
		t.Fatalf("temporary file was not removed: %v", err)
	}
}

func TestBadRecords(t *testing.T) {
	dir := t.TempDir()
	j := &Journal{Dir: dir}
	id2 := "22222222-2222-4222-8222-222222222222"
	id3 := "33333333-3333-4333-8333-333333333333"
	must := func(name, body string) {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(body), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	must(id1+".json", "{not json")
	must(id2+".json", `{"sandbox_id":"`+id3+`","state":"running"}`)
	must(id3+".json", `{"sandbox_id":"`+id3+`","state":"weird"}`)
	must("notes.txt", "ignored")
	recs, bad, err := j.Load()
	if err != nil || len(recs) != 0 || len(bad) != 3 {
		t.Fatalf("load: %v %v %v", recs, bad, err)
	}
	for _, b := range bad {
		if b.SandboxID == "" || b.Err == nil {
			t.Fatalf("bad file without id or error: %+v", b)
		}
	}
}
