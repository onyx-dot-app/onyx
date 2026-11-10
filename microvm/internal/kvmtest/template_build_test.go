//go:build kvm && linux

package kvmtest

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"

	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/hostinfo"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
	"github.com/onyx-dot-app/onyx/microvm/internal/tplbuild"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
	sdpb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// startTBAgent runs the agent binary in a privileged container (private
// cgroup namespace, like the DaemonSet) that builds its template from
// rootfsDir.
func startTBAgent(t *testing.T, e env, name, rootfsDir, ca, certDir string, certs *testcerts.Set) {
	t.Helper()
	bin := getenv("KVM_AGENT_BIN", "/opt/agent/host-agent")
	// The image needs mkfs.ext4 (e2fsprogs) for the template's empty drives.
	image := getenv("KVM_AGENT_IMAGE", "craft-fc-tb-agent:local")
	args := []string{"run", "-d", "--name", name, "--privileged", "--pid=host", "--cgroupns=private", "--network=host",
		"-v", e.DataDir + ":" + e.DataDir,
		"-v", e.ArtifactsDir + ":" + e.ArtifactsDir + ":ro",
		"-v", filepath.Dir(bin) + ":" + filepath.Dir(bin) + ":ro",
		"-v", filepath.Dir(ca) + ":" + filepath.Dir(ca) + ":ro",
		"-v", certDir + ":" + certDir + ":ro",
		image, bin, "--data-dir", e.DataDir, "--artifacts-dir", e.ArtifactsDir,
		"--listen", ptListen, "--tls-cert", certs.ServerCert, "--tls-key", certs.ServerKey, "--client-ca", certs.ClientCA,
		"--rootfs-dir", rootfsDir, "--egress-ca", ca,
		"--template-vcpus", fmt.Sprint(tplVCPUs), "--template-mem-mib", fmt.Sprint(tplMemMiB), "--template-scratch-gib", fmt.Sprint(tplScratchGiB)}
	if out, err := exec.Command("docker", args...).CombinedOutput(); err != nil {
		t.Fatalf("docker run: %v: %s", err, out)
	}
}

// putRootfs replaces the agent's --rootfs-dir content with a copy of src
// (a build-rootfs.sh output). With label set, the copy gets that ext4 label,
// so it is another root drive build (other SHA256), and the manifest says so.
func putRootfs(t *testing.T, src, dst, label string) {
	t.Helper()
	if err := os.RemoveAll(dst); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(dst, 0o755); err != nil {
		t.Fatal(err)
	}
	img := filepath.Join(dst, tplbuild.RootfsImageFile)
	if out, err := exec.Command("cp", "--reflink=auto", "--sparse=always", filepath.Join(src, tplbuild.RootfsImageFile), img).CombinedOutput(); err != nil {
		t.Fatalf("cp: %v %s", err, out)
	}
	raw, err := os.ReadFile(filepath.Join(src, tplbuild.RootfsManifestFile))
	if err != nil {
		t.Fatal(err)
	}
	if label != "" {
		if out, err := exec.Command("e2label", img, label).CombinedOutput(); err != nil {
			t.Fatalf("e2label: %v %s", err, out)
		}
		sum, err := template.FileSHA256(img)
		if err != nil {
			t.Fatal(err)
		}
		var m map[string]any
		if err := json.Unmarshal(raw, &m); err != nil {
			t.Fatal(err)
		}
		out := m["output"].(map[string]any)
		out["sha256"], out["fs_label"] = sum, label
		if raw, err = json.MarshalIndent(m, "", "  "); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(dst, tplbuild.RootfsManifestFile), raw, 0o644); err != nil {
		t.Fatal(err)
	}
}

var builtRE = regexp.MustCompile(`"msg":"template built".*`)

func templateNames(t *testing.T, dir string) []string {
	t.Helper()
	ents, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	var out []string
	for _, e := range ents {
		if e.IsDir() {
			out = append(out, e.Name())
		}
	}
	slices.Sort(out)
	return out
}

func memAvailMiB(t *testing.T) uint64 {
	t.Helper()
	_, avail, err := hostinfo.Stats{}.MemInfo()
	if err != nil {
		t.Fatal(err)
	}
	return avail
}

// TestTemplateBuildKVM checks the per-node template pipeline (ENG-4566)
// through the agent binary: build from a build-rootfs.sh output, restore 20
// VMs (Init + Run through the pass-through), refuse a tampered template and a
// template with another node key, and keep 2 templates.
func TestTemplateBuildKVM(t *testing.T) {
	e := loadEnv()
	_ = newCommand(t, e)
	ctx, cancel := context.WithTimeout(context.Background(), 40*time.Minute)
	defer cancel()
	src := getenv("KVM_TB_ROOTFS", "/opt/tb/rootfs-out")
	ca := getenv("KVM_TB_CA", "/opt/tb/ca/ca.crt")
	certDir := getenv("KVM_CERT_DIR", "/opt/tb/certs")
	logDir := getenv("KVM_LOG_DIR", "/var/log/bench")
	rootfsDir := filepath.Join(e.DataDir, "rootfs")
	tplDir := filepath.Join(e.DataDir, "templates")
	lay := jailer.Layout{ChrootBase: filepath.Join(e.DataDir, "jail")}
	n := e.VMs

	_ = exec.Command("docker", "rm", "-f", "tb-a1", "tb-a2").Run()
	t.Cleanup(func() { _ = exec.Command("docker", "rm", "-f", "tb-a1", "tb-a2").Run() })
	if err := os.RemoveAll(tplDir); err != nil {
		t.Fatal(err)
	}
	if err := os.RemoveAll(rootfsDir); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(certDir, 0o700); err != nil {
		t.Fatal(err)
	}
	certs, err := testcerts.Write(certDir)
	if err != nil {
		t.Fatal(err)
	}

	// 1. The agent starts with an empty --rootfs-dir: no template yet.
	startTBAgent(t, e, "tb-a1", rootfsDir, ca, certDir, certs)
	conn := ptConn(t, ctx, certs, "tb-a1")
	ha, sd := pb.NewHostAgentClient(conn), sdpb.NewSandboxdClient(conn)
	if _, l := logLine(containerLogs("tb-a1"), "template build at start-up failed"); l != "" {
		t.Logf("agent with no root drive: %s", l)
	}

	// 2. Build from the real build-rootfs.sh output.
	putRootfs(t, src, rootfsDir, "")
	t0 := time.Now()
	br, err := ha.BuildTemplate(ctx, &pb.BuildTemplateRequest{})
	if err != nil {
		t.Fatalf("build: %v\nagent logs:\n%s", err, containerLogs("tb-a1"))
	}
	buildWall := time.Since(t0)
	tplA := br.GetTemplate()
	_, built := logLine(containerLogs("tb-a1"), `"msg":"template built"`)
	t.Logf("BENCH template_build_ms=%d (call %d ms) built=%v template=%s", br.GetBuildMs(), buildWall.Milliseconds(), br.GetBuilt(), tplA.GetVersion())
	t.Logf("agent: %s", builtRE.FindString(built))
	t.Logf("template key: image=%s digest=%s rootfs=%s ca=%s compatible=%v", tplA.GetImageRef(), tplA.GetImageDigest(),
		tplA.GetRootfsSha256()[:16], tplA.GetCaFingerprint()[:16], tplA.GetCompatible())
	if !br.GetBuilt() || !tplA.GetCompatible() {
		t.Fatalf("build result %v", br)
	}
	t0 = time.Now()
	br2, err := ha.BuildTemplate(ctx, &pb.BuildTemplateRequest{})
	if err != nil || br2.GetBuilt() || br2.GetTemplate().GetVersion() != tplA.GetVersion() {
		t.Fatalf("second build: %v %v", br2, err)
	}
	t.Logf("BENCH build_again_valid_ms=%d (template kept, no boot)", time.Since(t0).Milliseconds())
	raw, err := os.ReadFile(filepath.Join(tplDir, tplA.GetVersion(), template.ManifestFile))
	if err != nil {
		t.Fatal(err)
	}
	_ = os.WriteFile(filepath.Join(logDir, "tb-manifest-a.json"), raw, 0o644)

	create := func(id, key, tpl string) (*pb.VM, time.Duration, error) {
		t0 := time.Now()
		r, err := ha.Create(ctx, &pb.CreateRequest{SandboxId: id, Attempt: 1, Template: tpl,
			Vcpus: tplVCPUs, MemMib: tplMemMiB, ScratchGib: scratchGiB, TenantId: "public", SandboxdKey: key})
		return r.GetVm(), time.Since(t0), err
	}
	initRun := func(id, key string, gen uint64) (time.Duration, error) {
		t0 := time.Now()
		ent := make([]byte, 64)
		_, _ = rand.Read(ent)
		ir, err := sd.Init(vmCtx(ctx, id, key), &sdpb.InitRequest{HostTime: timestamppb.Now(), Entropy: ent,
			SandboxId: id, Generation: gen, SessionIds: []string{"s1"}, ScratchBytes: scratchGiB << 30})
		if err != nil {
			return 0, fmt.Errorf("init: %w", err)
		}
		if !ir.GetAttached() {
			return 0, fmt.Errorf("init did not attach the drives: %+v", ir)
		}
		r, err := ptRun(vmCtx(ctx, id, key), sd, "sh", "-c", "echo hello; grep -c ' /workspace/managed ' /proc/mounts")
		if err != nil || r.stdout != "hello\n1\n" || r.res.GetExitCode() != 0 {
			return 0, fmt.Errorf("run: %v %q %v", err, r.stdout, r.res)
		}
		h, err := sd.Health(vmCtx(ctx, id, key), &sdpb.HealthRequest{})
		if err != nil || h.GetGeneration() != gen || h.GetSandboxId() != id {
			return 0, fmt.Errorf("health %v %v", h, err)
		}
		return time.Since(t0), nil
	}
	stop := func(vm *pb.VM) {
		if _, err := ha.Stop(ctx, &pb.StopRequest{SandboxId: vm.GetSandboxId(), Attempt: vm.GetAttempt(), Generation: vm.GetGeneration()}); err != nil {
			t.Errorf("stop %s: %v", vm.GetSandboxId(), err)
		}
	}

	// 3. Restore n VMs at once, then Init + Run each through the pass-through.
	memBefore := memAvailMiB(t)
	ids, keys := make([]string, n), make([]string, n)
	vms := make([]*pb.VM, n)
	createMS := make([]float64, n)
	errs := make([]error, n)
	var wg sync.WaitGroup
	for i := range ids {
		ids[i], keys[i] = newUUID(), randKey()
		wg.Go(func() {
			var d time.Duration
			vms[i], d, errs[i] = create(ids[i], keys[i], tplA.GetVersion())
			createMS[i] = msOf(d)
		})
	}
	wg.Wait()
	for i, err := range errs {
		if err != nil {
			t.Fatalf("create %d: %v\nagent logs:\n%s", i, err, containerLogs("tb-a1"))
		}
	}
	t.Logf("BENCH restore_ms n=%d (all at once) p50=%.1f p95=%.1f max=%.1f", n, pctl(createMS, 0.5), pctl(createMS, 0.95), pctl(createMS, 1))
	var irMS []float64
	for i := range ids {
		d, err := initRun(ids[i], keys[i], vms[i].GetGeneration())
		if err != nil {
			t.Fatalf("vm %d: %v", i, err)
		}
		irMS = append(irMS, msOf(d))
	}
	t.Logf("BENCH init_run_health_ms n=%d p50=%.1f p95=%.1f max=%.1f", n, pctl(irMS, 0.5), pctl(irMS, 0.95), pctl(irMS, 1))
	memAfter := memAvailMiB(t)
	t.Logf("BENCH host_mem_per_vm_mib=%.0f (MemAvailable %d -> %d MiB for %d VMs after Init + Run)",
		float64(int64(memBefore)-int64(memAfter))/float64(n), memBefore, memAfter, n)

	// No hard links: each VM file is its own inode with one link.
	linked := 0
	tplIno := map[string]uint64{}
	for _, f := range template.Files {
		st, err := os.Stat(filepath.Join(tplDir, tplA.GetVersion(), f))
		if err != nil {
			t.Fatal(err)
		}
		s := st.Sys().(*syscall.Stat_t)
		tplIno[f] = s.Ino
		if s.Nlink != 1 {
			linked++
			t.Errorf("template %s has %d links", f, s.Nlink)
		}
	}
	for _, id := range ids {
		for _, f := range template.Files {
			st, err := os.Stat(lay.HostPath(id, "/"+f))
			if err != nil {
				t.Fatal(err)
			}
			s := st.Sys().(*syscall.Stat_t)
			if s.Nlink != 1 || s.Ino == tplIno[f] {
				linked++
			}
		}
	}
	t.Logf("no-hardlink check: %d VM files, %d linked to the template", n*len(template.Files), linked)
	if linked != 0 {
		t.Errorf("%d linked files", linked)
	}
	for _, vm := range vms {
		stop(vm)
	}

	// Restore one at a time (page cache warm).
	var seqMS, seqIR []float64
	for i := 0; i < n; i++ {
		id, key := newUUID(), randKey()
		vm, d, err := create(id, key, tplA.GetVersion())
		if err != nil {
			t.Fatalf("sequential create %d: %v", i, err)
		}
		seqMS = append(seqMS, msOf(d))
		ir, err := initRun(id, key, vm.GetGeneration())
		if err != nil {
			t.Fatalf("sequential vm %d: %v", i, err)
		}
		seqIR = append(seqIR, msOf(ir))
		stop(vm)
	}
	t.Logf("BENCH restore_ms n=%d (one at a time) p50=%.1f p95=%.1f max=%.1f", n, pctl(seqMS, 0.5), pctl(seqMS, 0.95), pctl(seqMS, 1))
	t.Logf("BENCH init_run_health_ms n=%d (one at a time) p50=%.1f p95=%.1f max=%.1f", n, pctl(seqIR, 0.5), pctl(seqIR, 0.95), pctl(seqIR, 1))

	// 4. A tampered template file is refused before the restore.
	t.Run("tampered", func(t *testing.T) {
		mem := filepath.Join(tplDir, tplA.GetVersion(), template.MemFile)
		f, err := os.OpenFile(mem, os.O_RDWR, 0)
		if err != nil {
			t.Fatal(err)
		}
		b := make([]byte, 1)
		off := int64(1 << 30)
		if _, err := f.ReadAt(b, off); err != nil {
			t.Fatal(err)
		}
		b[0] ^= 0xff
		if _, err := f.WriteAt(b, off); err != nil {
			t.Fatal(err)
		}
		_ = f.Close()
		t0 := time.Now()
		_, _, err = create(newUUID(), randKey(), tplA.GetVersion())
		t.Logf("create from a template with 1 flipped byte in mem (%d ms): %s: %v", time.Since(t0).Milliseconds(), apierr.FromStatus(err), err)
		if apierr.FromStatus(err) != pb.ErrorReason_TEMPLATE_INCOMPATIBLE || !strings.Contains(err.Error(), "mem") {
			t.Fatalf("tampered template: %v", err)
		}
		// BuildTemplate replaces it.
		r, err := ha.BuildTemplate(ctx, &pb.BuildTemplateRequest{})
		if err != nil || !r.GetBuilt() || r.GetTemplate().GetVersion() != tplA.GetVersion() {
			t.Fatalf("rebuild: %v %v", r, err)
		}
		t.Logf("BENCH template_rebuild_ms=%d", r.GetBuildMs())
		id, key := newUUID(), randKey()
		vm, _, err := create(id, key, tplA.GetVersion())
		if err != nil {
			t.Fatal(err)
		}
		if _, err := initRun(id, key, vm.GetGeneration()); err != nil {
			t.Fatal(err)
		}
		stop(vm)
		t.Logf("rebuilt template restores and runs")
	})

	// 5. A template whose key does not fit this node is refused, also when its
	// manifest is consistent.
	t.Run("mismatched_key", func(t *testing.T) {
		store := &template.Store{Dir: tplDir}
		orig, err := store.Get(tplA.GetVersion())
		if err != nil {
			t.Fatal(err)
		}
		for _, c := range []struct{ name, cpu string }{{"x-cpu", "AMD EPYC 9R14 96-Core Processor"}} {
			dir := filepath.Join(tplDir, c.name)
			_ = os.RemoveAll(dir)
			if err := os.MkdirAll(dir, 0o755); err != nil {
				t.Fatal(err)
			}
			for _, f := range template.Files {
				if out, err := exec.Command("cp", "--reflink=always", orig.Path(f), filepath.Join(dir, f)).CombinedOutput(); err != nil {
					t.Fatalf("cp: %v %s", err, out)
				}
			}
			k := orig.Key
			k.CPUModel = c.cpu
			if _, _, err := template.Seal(dir, template.Manifest{Version: c.name, Key: k, BuiltAt: orig.BuiltAt.Add(-time.Hour)}, orig.Files); err != nil {
				t.Fatal(err)
			}
			_, _, err := create(newUUID(), randKey(), c.name)
			t.Logf("create from a template built for %q: %s: %v", c.cpu, apierr.FromStatus(err), err)
			if apierr.FromStatus(err) != pb.ErrorReason_TEMPLATE_INCOMPATIBLE || !strings.Contains(err.Error(), "cpu model") {
				t.Errorf("mismatched key: %v", err)
			}
			// Forge it: the key says this node's CPU, the key hash is the old one.
			raw, _ := os.ReadFile(filepath.Join(dir, template.ManifestFile))
			var m template.Manifest
			_ = json.Unmarshal(raw, &m)
			m.CPUModel = hostinfo.CPUModel()
			if err := template.WriteManifest(dir, m); err != nil {
				t.Fatal(err)
			}
			_, _, err = create(newUUID(), randKey(), c.name)
			t.Logf("create from a forged manifest (key edited, key hash not): %s: %v", apierr.FromStatus(err), err)
			if apierr.FromStatus(err) != pb.ErrorReason_TEMPLATE_INCOMPATIBLE {
				t.Errorf("forged manifest: %v", err)
			}
			_ = os.RemoveAll(dir)
		}
		ni, err := ha.NodeInfo(ctx, &pb.NodeInfoRequest{})
		if err != nil {
			t.Fatal(err)
		}
		t.Logf("node: cpu %q, firecracker %s, host kernel %s", ni.GetCpuModel(), ni.GetFirecrackerVersion(), ni.GetHostKernel())
	})

	// 6. GC keeps the 2 newest templates and the ones that VMs use.
	t.Run("gc_keeps_2", func(t *testing.T) {
		idA, keyA := newUUID(), randKey()
		vmA, _, err := create(idA, keyA, tplA.GetVersion())
		if err != nil {
			t.Fatal(err)
		}
		if _, err := initRun(idA, keyA, vmA.GetGeneration()); err != nil {
			t.Fatal(err)
		}
		var names []string
		for _, label := range []string{"craft-root-b", "craft-root-c"} {
			putRootfs(t, src, rootfsDir, label)
			r, err := ha.BuildTemplate(ctx, &pb.BuildTemplateRequest{})
			if err != nil || !r.GetBuilt() {
				t.Fatalf("build %s: %v %v", label, r, err)
			}
			names = append(names, r.GetTemplate().GetVersion())
			t.Logf("built %s (%d ms) for root drive %s; removed %v; on disk %v", r.GetTemplate().GetVersion(), r.GetBuildMs(),
				label, r.GetRemoved(), templateNames(t, tplDir))
		}
		got := templateNames(t, tplDir)
		want := []string{tplA.GetVersion(), names[0], names[1]}
		slices.Sort(want)
		t.Logf("with a VM on %s: %d templates on disk (2 newest + 1 in use)", tplA.GetVersion(), len(got))
		if !slices.Equal(got, want) {
			t.Errorf("templates %v, want %v", got, want)
		}
		// The old template still runs its VM.
		if r, err := ptRun(vmCtx(ctx, idA, keyA), sd, "echo", "alive"); err != nil || r.stdout != "alive\n" {
			t.Errorf("VM on the old template: %v %q", err, r.stdout)
		}
		stop(vmA)

		// Agent restart: build-on-start finds the template valid (full hash
		// after a restart) and GC removes the template no VM uses.
		tStop := time.Now()
		if out, err := exec.Command("docker", "stop", "-t", "10", "tb-a1").CombinedOutput(); err != nil {
			t.Fatalf("docker stop: %v %s", err, out)
		}
		_ = os.WriteFile(filepath.Join(logDir, "tb-a1.log"), []byte(containerLogs("tb-a1")), 0o644)
		_ = exec.Command("docker", "rm", "tb-a1").Run()
		startTBAgent(t, e, "tb-a2", rootfsDir, ca, certDir, certs)
		conn2 := ptConn(t, ctx, certs, "tb-a2")
		ha = pb.NewHostAgentClient(conn2)
		r, err := ha.BuildTemplate(ctx, &pb.BuildTemplateRequest{})
		if err != nil || r.GetBuilt() || r.GetTemplate().GetVersion() != names[1] {
			t.Fatalf("after restart: %v %v", r, err)
		}
		_, ready := logLine(containerLogs("tb-a2"), `"msg":"template ready"`)
		t.Logf("BENCH restart_to_template_ready_ms=%d; agent: %s", time.Since(tStop).Milliseconds(), ready)
		got = templateNames(t, tplDir)
		want = []string{names[0], names[1]}
		slices.Sort(want)
		t.Logf("after restart: templates on disk %v", got)
		if !slices.Equal(got, want) {
			t.Errorf("templates %v, want %v", got, want)
		}
	})

	l, _ := ha.List(ctx, &pb.ListRequest{})
	for _, vm := range l.GetVms() {
		stop(vm)
	}
	left := 0
	if out, err := exec.Command("pgrep", "-c", "firecracker").Output(); err == nil {
		_, _ = fmt.Sscanf(strings.TrimSpace(string(out)), "%d", &left)
	}
	chroots, _ := os.ReadDir(filepath.Join(e.DataDir, "jail", "firecracker"))
	t.Logf("leftovers: %d Firecracker processes, %d chroots", left, len(chroots))
	_ = os.WriteFile(filepath.Join(logDir, "tb-a2.log"), []byte(containerLogs("tb-a2")), 0o644)
}
