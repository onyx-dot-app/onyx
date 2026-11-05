package fcvm

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

const cgID = "11111111-1111-4111-8111-111111111111"

func TestScopeIDBothNamespaceForms(t *testing.T) {
	host := CgroupView{}
	pod := CgroupView{Private: true}
	for _, tc := range []struct {
		body       string
		host, priv bool
	}{
		{"0::/fcvms.slice/fcvm-" + cgID + ".scope\n", true, false},
		{"0::/../../fcvms.slice/fcvm-" + cgID + ".scope\n", false, true},
		{"0::/../fcvms.slice/fcvm-" + cgID + ".scope", false, true},
		// Not a VM scope, or not ours.
		{"0::/../../kubepods.slice/fcvm-" + cgID + ".scope", false, false},
		{"0::/../../fcvms.slice/x/fcvm-" + cgID + ".scope", false, false},
		{"0::/../../fcvms.slice/fcvm-.scope", false, false},
		{"0::/fcvms.slice/fcvm-" + cgID + ".scope/child", false, false},
		{"0::/../a/../fcvms.slice/fcvm-" + cgID + ".scope", false, false},
		{"1:cpu:/fcvms.slice/fcvm-" + cgID + ".scope", false, false},
		{"0::/fcvms.slice/fcvm-" + cgID + ".scope\n0::/x\n", false, false},
	} {
		if id, ok := host.scopeID(tc.body, "fcvms.slice"); ok != tc.host || (ok && id != cgID) {
			t.Errorf("host view %q: %q %v", tc.body, id, ok)
		}
		if id, ok := pod.scopeID(tc.body, "fcvms.slice"); ok != tc.priv || (ok && id != cgID) {
			t.Errorf("private view %q: %q %v", tc.body, id, ok)
		}
	}
}

// TestVMScopeConfirmsInHostTree: in a private namespace a match counts only
// if the host's scope lists the PID. A read error is never a match.
func TestVMScopeConfirmsInHostTree(t *testing.T) {
	root := t.TempDir()
	v := CgroupView{Private: true, HostCgroupFS: root}
	scope := filepath.Join(root, "fcvms.slice", "fcvm-"+cgID+".scope")
	body := "0::/../../fcvms.slice/fcvm-" + cgID + ".scope\n"

	// No scope in the host tree: the process is gone.
	if _, ok, err := v.vmScope(body, "fcvms.slice", 4242); ok || !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("missing scope: %v %v", ok, err)
	}
	if err := os.MkdirAll(scope, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(scope, "cgroup.procs"), []byte("17\n4242\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if id, ok, err := v.vmScope(body, "fcvms.slice", 4242); err != nil || !ok || id != cgID {
		t.Fatalf("listed pid: %q %v %v", id, ok, err)
	}
	// Another cgroup with the same relative name: the host scope does not
	// list the PID.
	if _, ok, err := v.vmScope(body, "fcvms.slice", 999); err != nil || ok {
		t.Fatalf("unlisted pid: %v %v", ok, err)
	}
	// An unreadable cgroup.procs is an error, not "not ours".
	if err := os.Remove(filepath.Join(scope, "cgroup.procs")); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(scope, "cgroup.procs"), 0o755); err != nil {
		t.Fatal(err)
	}
	if _, ok, err := v.vmScope(body, "fcvms.slice", 4242); err == nil || ok || errors.Is(err, os.ErrNotExist) {
		t.Fatalf("unreadable procs: %v %v", ok, err)
	}
	// The host view needs no host tree.
	if id, ok, err := (CgroupView{}).vmScope("0::/fcvms.slice/fcvm-"+cgID+".scope", "fcvms.slice", 1); err != nil || !ok || id != cgID {
		t.Fatalf("host view: %q %v %v", id, ok, err)
	}
}

func TestDetectCgroupView(t *testing.T) {
	proc := t.TempDir()
	for _, d := range []string{"self/ns", "1/ns"} {
		if err := os.MkdirAll(filepath.Join(proc, d), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	link := func(pid, target string) {
		t.Helper()
		p := filepath.Join(proc, pid, "ns", "cgroup")
		_ = os.Remove(p)
		if err := os.Symlink(target, p); err != nil {
			t.Fatal(err)
		}
	}
	link("self", "cgroup:[4026531835]")
	link("1", "cgroup:[4026531835]")
	if v, err := DetectCgroupView(proc); err != nil || v.Private {
		t.Fatalf("same namespace: %+v %v", v, err)
	}
	link("self", "cgroup:[4026532999]")
	if v, err := DetectCgroupView(proc); err == nil {
		t.Fatalf("private namespace without a host tree worked: %+v", v)
	}
	host := filepath.Join(proc, "1", "root", "sys", "fs", "cgroup")
	if err := os.MkdirAll(host, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(host, "cgroup.controllers"), []byte("cpu memory\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if v, err := DetectCgroupView(proc); err != nil || !v.Private || v.HostCgroupFS != host {
		t.Fatalf("private namespace: %+v %v", v, err)
	}
	if err := os.Remove(filepath.Join(proc, "1", "ns", "cgroup")); err != nil {
		t.Fatal(err)
	}
	if _, err := DetectCgroupView(proc); err == nil {
		t.Fatal("no PID 1 namespace worked")
	}
}
