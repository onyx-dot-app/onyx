//go:build kvm && linux

package kvmtest

import (
	"archive/tar"
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/klauspost/compress/zstd"
	"google.golang.org/genproto/googleapis/rpc/errdetails"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
	sdpb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// savesScratchGiB holds a 1 GiB session twice (the restore staging copy).
const savesScratchGiB = 8

// startSavesAgent runs the agent binary in a container with the mTLS
// listener and the host CA bundle (the agent image has ca-certificates).
func startSavesAgent(t *testing.T, e env, name, certDir string, certs *testcerts.Set) {
	t.Helper()
	bin := getenv("KVM_AGENT_BIN", "/opt/agent/host-agent")
	// The host CA bundle: AL2023, else Debian and Ubuntu.
	ca := os.Getenv("KVM_CA_BUNDLE")
	if ca == "" {
		ca = "/etc/pki/tls/certs/ca-bundle.crt"
		if !fileExists(ca) {
			ca = "/etc/ssl/certs/ca-certificates.crt"
		}
	}
	args := []string{"run", "-d", "--name", name, "--privileged", "--pid=host", "--cgroupns=private", "--network=host",
		"-v", e.DataDir + ":" + e.DataDir, "-v", certDir + ":" + certDir + ":ro",
		"-v", e.ArtifactsDir + ":" + e.ArtifactsDir + ":ro", "-v", filepath.Dir(bin) + ":" + filepath.Dir(bin) + ":ro",
		"-v", ca + ":/etc/ssl/certs/ca-certificates.crt:ro"}
	// The proxy CA, if there is one: the daemon installs it at Init. Without
	// it, the root drive must have a built-in CA.
	var caFlags []string
	confdir := getenv("KVM_PROXY_CONFDIR", "/opt/proxy/confdir")
	if proxyCA := filepath.Join(confdir, "mitmproxy-ca-cert.pem"); fileExists(proxyCA) {
		args = append(args, "-v", confdir+":"+confdir+":ro")
		caFlags = []string{"--egress-ca", proxyCA}
	}
	args = append(args, getenv("KVM_AGENT_IMAGE", "debian:trixie-slim"), bin,
		"--data-dir", e.DataDir, "--artifacts-dir", e.ArtifactsDir,
		"--listen", ptListen, "--tls-cert", certs.ServerCert, "--tls-key", certs.ServerKey, "--client-ca", certs.ClientCA,
		"--transfer-parallel", getenv("KVM_TRANSFER_PARALLEL", "8"))
	args = append(args, caFlags...)
	if out, err := exec.Command("docker", args...).CombinedOutput(); err != nil {
		t.Fatalf("docker run: %v: %s", err, out)
	}
}

func onPath(program string) bool {
	_, err := exec.LookPath(program)
	return err == nil
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

// presign signs a request the way FileStore does (KVM_PRESIGN: presign.py
// with the host's credentials; the agent only gets the result).
func presign(t *testing.T, args ...string) *pb.PresignedRequest {
	t.Helper()
	out, err := exec.Command(getenv("KVM_PRESIGN", "/opt/df/presign.py"), args...).Output()
	if err != nil {
		var ee *exec.ExitError
		if errors.As(err, &ee) {
			t.Fatalf("presign %v: %v: %s", args[:2], err, ee.Stderr)
		}
		t.Fatalf("presign: %v", err)
	}
	var r struct {
		URL     string            `json:"url"`
		Method  string            `json:"method"`
		Headers map[string]string `json:"headers"`
	}
	if err := json.Unmarshal(out, &r); err != nil {
		t.Fatalf("presign output: %v", err)
	}
	return &pb.PresignedRequest{Url: r.URL, Method: r.Method, Headers: r.Headers}
}

type savesVM struct {
	id, key string
	vm      *pb.VM
	ctx     context.Context
}

type savesEnv struct {
	t      *testing.T
	e      env
	ha     pb.HostAgentClient
	sd     sdpb.SandboxdClient
	bucket string
	vms    []*savesVM
}

// newVM creates a VM from the template and runs CloseConnections and Init:
// the api_server bring-up. It returns the times of each step.
func (s *savesEnv) newVM(ctx context.Context, sessions ...string) (*savesVM, [3]time.Duration) {
	s.t.Helper()
	var d [3]time.Duration
	v := &savesVM{id: newUUID(), key: randKey()}
	t0 := time.Now()
	r, err := s.ha.Create(ctx, &pb.CreateRequest{SandboxId: v.id, Attempt: 1, Template: s.e.Template, Vcpus: tplVCPUs,
		MemMib: tplMemMiB, ScratchGib: savesScratchGiB, TenantId: "public", SandboxdKey: v.key})
	if err != nil {
		s.t.Fatalf("create: %v", err)
	}
	d[0] = time.Since(t0)
	v.vm, v.ctx = r.GetVm(), vmCtx(ctx, v.id, v.key)
	s.vms = append(s.vms, v)
	t1 := time.Now()
	if _, err := s.ha.CloseConnections(ctx, &pb.CloseConnectionsRequest{SandboxId: v.id, Attempt: 1, Generation: v.vm.GetGeneration()}); err != nil {
		s.t.Fatalf("close connections: %v", err)
	}
	d[1] = time.Since(t1)
	ent := make([]byte, 64)
	_, _ = rand.Read(ent)
	t2 := time.Now()
	if _, err := s.sd.Init(v.ctx, &sdpb.InitRequest{HostTime: timestamppb.Now(), Entropy: ent, SandboxId: v.id,
		Generation: v.vm.GetGeneration(), SessionIds: sessions, ScratchBytes: savesScratchGiB << 30}); err != nil {
		s.t.Fatalf("init: %v", err)
	}
	d[2] = time.Since(t2)
	return v, d
}

func (s *savesEnv) stop(ctx context.Context, v *savesVM) {
	s.t.Helper()
	if _, err := s.ha.Stop(ctx, &pb.StopRequest{SandboxId: v.id, Attempt: 1, Generation: v.vm.GetGeneration()}); err != nil {
		s.t.Errorf("stop %s: %v", v.id, err)
	}
}

func (s *savesEnv) run(v *savesVM, script string) string {
	s.t.Helper()
	r, err := ptRun(v.ctx, s.sd, "bash", "-c", script)
	if err != nil || r.res.GetExitCode() != 0 {
		s.t.Fatalf("run %q: %v exit=%d stderr=%s", script[:min(len(script), 60)], err, r.res.GetExitCode(), r.stderr)
	}
	return strings.TrimSpace(r.stdout)
}

func (s *savesEnv) capture(ctx context.Context, v *savesVM, session string) *pb.CaptureSessionResponse {
	s.t.Helper()
	cr, err := s.ha.CaptureSession(ctx, &pb.CaptureSessionRequest{SandboxId: v.id, Attempt: 1, Generation: v.vm.GetGeneration(),
		SandboxdKey: v.key, SessionId: session})
	if err != nil {
		s.t.Fatalf("capture: %v", err)
	}
	return cr
}

func (s *savesEnv) restore(ctx context.Context, v *savesVM, session, key string, size int64, sha string) (*pb.RestoreSessionResponse, error) {
	return s.ha.RestoreSession(ctx, &pb.RestoreSessionRequest{SandboxId: v.id, Attempt: 1, Generation: v.vm.GetGeneration(),
		SandboxdKey: v.key, SessionId: session, Request: presign(s.t, "get", s.bucket, key), SizeBytes: size, Sha256: sha})
}

// manifestScript prints one hash over every file path, mode and content of
// the session's capture roots, and the file count.
// It leaves out what a capture leaves out (node_modules, .venv, .next).
const manifestScript = `cd /workspace/sessions/%s && P='( -name node_modules -o -name .venv -o -name .next ) -prune -o' && \
  find attachments $P -type f -printf '%%m %%p\n' | LC_ALL=C sort > /tmp/m.list && \
  (cat /tmp/m.list; find attachments $P -type f -print0 | LC_ALL=C sort -z | xargs -0 cat) | sha256sum | cut -c1-16; wc -l < /tmp/m.list`

// costScript times guest-only steps with a cold page cache: tar | zstd -3
// to a file on the scratch disk, zstd -d of that file, a local extract, and
// a 1 GiB write with fdatasync.
const costScript = `cd /workspace/sessions/%s; t() { sync; echo 3 > /proc/sys/vm/drop_caches; s=$(date +%%s%%N); eval "$1" >/dev/null; echo "$2=$(( ($(date +%%s%%N)-s)/1000000 ))ms"; }
t 'tar cf - attachments | zstd -3 -T0 -q -c > /mnt/scratch/a.zst' tar_zstd3_to_disk
t 'zstd -d -q -c /mnt/scratch/a.zst' zstd_decode
t 'mkdir -p /mnt/scratch/x && zstd -d -q -c /mnt/scratch/a.zst | tar x -C /mnt/scratch/x && sync' local_extract_sync
t 'dd if=/dev/zero of=/mnt/scratch/dd bs=1M count=1024 conv=fdatasync status=none' dd_1gib_fdatasync
rm -rf /mnt/scratch/a.zst /mnt/scratch/x /mnt/scratch/dd`

// genFiles makes a 1 GiB session of user files (no dependencies): text
// documents, CSV, images (random, incompressible), small source files and
// attachments.
const genFiles = `import os, base64, sys
s = "/workspace/sessions/" + sys.argv[1]
def w(p, b):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(b)
for i in range(150):  # 300 MiB of text docs
    w(f"{s}/attachments/docs/report_{i:03}.md", base64.b64encode(os.urandom(1536 * 1024))[: 2 << 20])
for i in range(50):   # 200 MiB of CSV
    w(f"{s}/attachments/data/table_{i:02}.csv", "".join(f"{r},{r*7%1000},{r*13%997},name_{r%5000}\n" for r in range(i * 100000, i * 100000 + 140000)).encode()[: 4 << 20])
for i in range(120):  # 480 MiB of images
    w(f"{s}/attachments/images/img_{i:03}.png", os.urandom(4 << 20))
for i in range(5000): # 20 MiB of small source files
    w(f"{s}/attachments/web/src/c{i//100}/f{i}.tsx", f"export const v{i} = {i};\n".encode() * 160)
for i in range(30):   # 30 MiB of attachments
    w(f"{s}/attachments/upload_{i}.pdf", os.urandom(1 << 20))
print("GEN_DONE")
`

// genT2 makes the T2 session: 1 GiB, mostly dependencies (node_modules,
// .venv, .next) that a capture leaves out, plus ~90 MiB of user files.
const genT2 = `import os, base64, sys
s = "/workspace/sessions/" + sys.argv[1]
def w(p, b):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(b)
txt = lambda n: base64.b64encode(os.urandom(n * 3 // 4 + 3))[:n]
for i in range(40000):  # ~730 MiB node_modules in 40k files
    w(f"{s}/attachments/web/node_modules/pkg{i//200}/lib/m{i}.js", txt(19 * 1024))
for i in range(5000):   # ~170 MiB venv
    w(f"{s}/attachments/.venv/lib/python3.11/site-packages/p{i//50}/m{i}.py", txt(35 * 1024))
w(f"{s}/attachments/.venv/pyvenv.cfg", b"home = /usr/bin\n")
for i in range(400):    # ~40 MiB .next
    w(f"{s}/attachments/web/.next/cache/c{i}", txt(100 * 1024))
for i in range(300):    # 48 MiB docs
    w(f"{s}/attachments/docs/d{i}.md", txt(160 * 1024))
for i in range(39):     # 39 MiB images
    w(f"{s}/attachments/images/i{i}.jpg", os.urandom(1 << 20))
for i in range(800):    # app source
    w(f"{s}/attachments/web/src/f{i}.tsx", txt(4 * 1024))
w(f"{s}/attachments/brief.pdf", os.urandom(2 << 20))
print("GEN_DONE")
`

// TestSavesKVM runs the file calls and session saves through the
// node agent over mTLS with a real S3 bucket (presigned URLs).
func TestSavesKVM(t *testing.T) {
	e := loadEnv()
	bucket := os.Getenv("KVM_S3_BUCKET")
	if bucket == "" {
		t.Skip("KVM_S3_BUCKET not set: the saves test needs a test S3 bucket and AWS credentials")
	}
	if p := getenv("KVM_PRESIGN", "/opt/df/presign.py"); !onPath(p) {
		t.Fatalf("no presigner %s: set KVM_PRESIGN to a program that prints a presigned request", p)
	}
	e.Template = getenv("KVM_SAVES_TEMPLATE", "kvmtest-saves-1")
	cmd := newCommand(t, e)
	buildTemplateWith(t, &e, cmd, getenv("KVM_PT_BOOT_ARGS", ptBootArgs), waitDaemon)
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Minute)
	defer cancel()
	samples := 3
	if v := os.Getenv("KVM_SAVES_SAMPLES"); v != "" {
		_, _ = fmt.Sscanf(v, "%d", &samples)
	}

	certDir := getenv("KVM_CERT_DIR", "/opt/df/certs")
	if err := os.MkdirAll(certDir, 0o700); err != nil {
		t.Fatal(err)
	}
	certs, err := testcerts.Write(certDir)
	if err != nil {
		t.Fatal(err)
	}
	_ = exec.Command("docker", "rm", "-f", "sv-a1").Run()
	t.Cleanup(func() {
		_ = os.WriteFile(filepath.Join(getenv("KVM_LOG_DIR", "/var/log/bench"), "sv-a1.log"), []byte(containerLogs("sv-a1")), 0o644)
		_ = exec.Command("docker", "rm", "-f", "sv-a1").Run()
	})
	startSavesAgent(t, e, "sv-a1", certDir, certs)
	conn := ptConn(t, ctx, certs, "sv-a1")
	s := &savesEnv{t: t, e: e, ha: pb.NewHostAgentClient(conn), sd: sdpb.NewSandboxdClient(conn), bucket: bucket}
	t.Cleanup(func() {
		cctx, ccancel := context.WithTimeout(context.Background(), 2*time.Minute)
		defer ccancel()
		for _, v := range s.vms {
			if alive(v.vm.GetPid()) {
				_, _ = s.ha.Stop(cctx, &pb.StopRequest{SandboxId: v.id, Attempt: 1, Generation: v.vm.GetGeneration()})
				killFirecracker(t, v.vm.GetPid())
			}
		}
	})

	sessFiles, sessT2 := newUUID(), newUUID()
	a, _ := s.newVM(ctx, sessFiles, sessT2)

	t.Run("file_calls", func(t *testing.T) { fileCallsKVM(t, ctx, s, a, sessFiles) })
	if bin := os.Getenv("KVM_GUEST_BENCH"); bin != "" {
		t.Run("guest_bench", func(t *testing.T) { guestBenchKVM(t, s, a, sessFiles, bin) })
	}

	for _, variant := range []struct {
		name, gen, session string
	}{{"files_1gib", genFiles, sessFiles}, {"t2_with_deps", genT2, sessT2}} {
		t.Run(variant.name, func(t *testing.T) {
			if out := s.run(a, "cat > /tmp/gen.py <<'EOF'\n"+variant.gen+"EOF\npython3 /tmp/gen.py "+variant.session); !strings.Contains(out, "GEN_DONE") {
				t.Fatalf("gen: %s", out)
			}
			du := s.run(a, "du -sb /workspace/sessions/"+variant.session+" | cut -f1; find /workspace/sessions/"+variant.session+" -type f | wc -l")
			src := s.run(a, fmt.Sprintf(manifestScript, variant.session))
			if variant.name == "files_1gib" {
				t.Logf("guest cost (cold cache, 2 vCPU): %s", strings.ReplaceAll(s.run(a, fmt.Sprintf(costScript, variant.session)), "\n", " "))
			}
			// Drop the guest page cache, so the capture reads the disk.
			s.run(a, "sync; echo 3 > /proc/sys/vm/drop_caches")
			cr := s.capture(ctx, a, variant.session)
			t.Logf("BENCH %s session_bytes,files=%s capture_ms=%d stored_bytes=%d expanded_bytes=%d files=%d excluded=%d skipped=%d",
				variant.name, strings.ReplaceAll(du, "\n", ","), cr.GetCaptureMs(), cr.GetSizeBytes(), cr.GetExpandedBytes(),
				cr.GetFiles(), cr.GetExcluded(), cr.GetSkipped())
			key := "eng-4572/" + variant.name + "/" + cr.GetCaptureId()
			t0 := time.Now()
			up, err := s.ha.UploadCapture(ctx, &pb.UploadCaptureRequest{CaptureId: cr.GetCaptureId(),
				Request: presign(t, "put", bucket, key, fmt.Sprint(cr.GetSizeBytes()), cr.GetSha256())})
			if err != nil {
				t.Fatalf("upload: %v", err)
			}
			t.Logf("BENCH %s upload_ms=%d (agent %d) status=%d etag=%s MB/s=%.0f", variant.name, time.Since(t0).Milliseconds(),
				up.GetUploadMs(), up.GetHttpStatus(), up.GetEtag(), float64(cr.GetSizeBytes())/1e6/time.Since(t0).Seconds())

			var restoreMS, readyMS []float64
			for i := 0; i < samples; i++ {
				t0 := time.Now()
				b, steps := s.newVM(ctx, variant.session)
				t1 := time.Now()
				rr, err := s.restore(ctx, b, variant.session, key, cr.GetSizeBytes(), cr.GetSha256())
				if err != nil {
					t.Fatalf("restore %d: %v", i, err)
				}
				rd := time.Since(t1)
				ready := time.Since(t0)
				restoreMS, readyMS = append(restoreMS, msOf(rd)), append(readyMS, msOf(ready))
				got := s.run(b, fmt.Sprintf(manifestScript, variant.session))
				if i == 0 {
					t.Logf("daemon: %s", s.run(b, "grep 'msg=restore' /run/craft-fc/log/guest-daemon.log | tail -1"))
					_, al := logLine(containerLogs("sv-a1"), `"msg":"session restored","sandbox_id":"`+b.id)
					t.Logf("agent: %s", al)
					// Again into the same VM: its guest memory is now backed on
					// the host, so this shows the cost of first-touch page faults.
					t2 := time.Now()
					if _, err := s.restore(ctx, b, variant.session, key, cr.GetSizeBytes(), cr.GetSha256()); err != nil {
						t.Fatalf("second restore: %v", err)
					}
					t.Logf("BENCH %s restore_again_same_vm_ms=%d", variant.name, time.Since(t2).Milliseconds())
				}
				t.Logf("restore %d: create=%d close=%d init=%d restore=%d (agent %d) ms, ready=%d ms, files=%d; manifest %s",
					i, steps[0].Milliseconds(), steps[1].Milliseconds(), steps[2].Milliseconds(), rd.Milliseconds(),
					rr.GetRestoreMs(), ready.Milliseconds(), rr.GetFiles(), strings.ReplaceAll(got, "\n", " "))
				if got != src {
					t.Errorf("restored manifest %q, source %q", got, src)
				}
				if left := s.run(b, "ls -A /workspace/sessions/"+variant.session+"/attachments/web 2>/dev/null | tr '\\n' ' '"); strings.Contains(left, "node_modules") || strings.Contains(left, ".next") {
					t.Errorf("dependencies restored: %s", left)
				}
				s.stop(ctx, b)
			}
			t.Logf("BENCH %s restore_ms n=%d p50=%.0f max=%.0f; create_to_restored_ms p50=%.0f max=%.0f", variant.name, samples,
				pctl(restoreMS, 0.5), pctl(restoreMS, 1), pctl(readyMS, 0.5), pctl(readyMS, 1))
		})
	}

	t.Run("restore_safety", func(t *testing.T) { restoreSafetyKVM(t, ctx, s, sessFiles) })
	s.stop(ctx, a)
}

func fileCallsKVM(t *testing.T, ctx context.Context, s *savesEnv, a *savesVM, session string) {
	data := make([]byte, 64<<20)
	_, _ = rand.Read(data)
	sum := sha256.Sum256(data)
	t0 := time.Now()
	ws, err := s.sd.WriteFile(a.ctx)
	if err != nil {
		t.Fatal(err)
	}
	_ = ws.Send(&sdpb.WriteFileRequest{Part: &sdpb.WriteFileRequest_Header{Header: &sdpb.WriteFileHeader{
		SessionId: session, Path: "attachments/blob.bin", Size: int64(len(data)), Sha256: hex.EncodeToString(sum[:]), MakeParents: true}}})
	for off := 0; off < len(data); off += 1 << 20 {
		if err := ws.Send(&sdpb.WriteFileRequest{Part: &sdpb.WriteFileRequest_Data{Data: data[off : off+1<<20]}}); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := ws.CloseAndRecv(); err != nil {
		t.Fatalf("write: %v", err)
	}
	wd := time.Since(t0)
	t0 = time.Now()
	rs, err := s.sd.ReadFile(a.ctx, &sdpb.ReadFileRequest{SessionId: session, Path: "attachments/blob.bin"})
	if err != nil {
		t.Fatal(err)
	}
	h := sha256.New()
	for {
		m, err := rs.Recv()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		h.Write(m.GetData())
	}
	rd := time.Since(t0)
	if !bytes.Equal(h.Sum(nil), sum[:]) {
		t.Fatal("read data differs")
	}
	t.Logf("BENCH write_64mib_ms=%d (%.0f MB/s) read_64mib_ms=%d (%.0f MB/s)", wd.Milliseconds(), 67.1/wd.Seconds(),
		rd.Milliseconds(), 67.1/rd.Seconds())

	var names []string
	var upMS []float64
	for i := 0; i < 3; i++ {
		t0 := time.Now()
		us, _ := s.sd.UploadFile(a.ctx)
		_ = us.Send(&sdpb.UploadFileRequest{Part: &sdpb.UploadFileRequest_Header{Header: &sdpb.UploadFileHeader{SessionId: session, FileName: "brief.pdf", Size: 5 << 20}}})
		_ = us.Send(&sdpb.UploadFileRequest{Part: &sdpb.UploadFileRequest_Data{Data: data[:1<<20]}})
		for j := 1; j < 5; j++ {
			_ = us.Send(&sdpb.UploadFileRequest{Part: &sdpb.UploadFileRequest_Data{Data: data[j<<20 : (j+1)<<20]}})
		}
		ur, err := us.CloseAndRecv()
		if err != nil {
			t.Fatalf("upload: %v", err)
		}
		upMS = append(upMS, msOf(time.Since(t0)))
		names = append(names, ur.GetInfo().GetPath())
	}
	t.Logf("upload 5 MiB x3: %v, p50 %.1f ms", names, pctl(upMS, 0.5))
	if strings.Join(names, ",") != "attachments/brief.pdf,attachments/brief_1.pdf,attachments/brief_2.pdf" {
		t.Errorf("upload names %v", names)
	}

	s.run(a, "mkdir -p /workspace/sessions/"+session+"/attachments/web/src && cd /workspace/sessions/"+session+
		"/attachments/web/src && for i in $(seq 1 2000); do echo \"export const a$i = $i;\" > f$i.ts; done; ln -sf /etc/shadow leak; echo ok")
	t0 = time.Now()
	lr, err := s.sd.ListFiles(a.ctx, &sdpb.ListFilesRequest{SessionId: session, Recursive: true, MaxEntries: 100000})
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("BENCH list_recursive_ms=%d entries=%d truncated=%v", time.Since(t0).Milliseconds(), len(lr.GetEntries()), lr.GetTruncated())
	t0 = time.Now()
	zs, err := s.sd.ZipFiles(a.ctx, &sdpb.ZipFilesRequest{SessionId: session, Path: "attachments/web"})
	if err != nil {
		t.Fatal(err)
	}
	var zipBytes int
	var zsum *sdpb.ZipSummary
	for {
		m, err := zs.Recv()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		zipBytes += len(m.GetData())
		if m.GetSummary() != nil {
			zsum = m.GetSummary()
		}
	}
	t.Logf("BENCH zip_ms=%d files=%d zip_bytes=%d skipped=%d (the /etc/shadow link)", time.Since(t0).Milliseconds(),
		zsum.GetFiles(), zipBytes, zsum.GetSkipped())
	if zsum.GetFiles() != 2000 || zsum.GetSkipped() != 1 {
		t.Errorf("zip summary %v", zsum)
	}
	// Escapes fail in the guest too.
	rs, _ = s.sd.ReadFile(a.ctx, &sdpb.ReadFileRequest{SessionId: session, Path: "attachments/web/src/leak"})
	if _, err := rs.Recv(); err == nil {
		t.Error("read through a link to /etc/shadow worked")
	}
	if _, err := s.sd.ListFiles(a.ctx, &sdpb.ListFilesRequest{SessionId: session, Path: "../../etc"}); err == nil {
		t.Error("list of ../../etc worked")
	}
	if dr, err := s.sd.DeleteFile(a.ctx, &sdpb.DeleteFileRequest{SessionId: session, Path: "attachments", Recursive: true}); err != nil || !dr.GetDeleted() {
		t.Fatalf("delete: %v %v", dr, err)
	}
	if out := s.run(a, "test -f /etc/shadow && echo present"); out != "present" {
		t.Error("/etc/shadow is gone after deleting a link to it")
	}
	s.run(a, "rm -rf /workspace/sessions/"+session+"/attachments")
}

func evilArchive(t *testing.T) []byte {
	var buf bytes.Buffer
	zw, _ := zstd.NewWriter(&buf)
	tw := tar.NewWriter(zw)
	add := func(h *tar.Header, data string) {
		if h.Typeflag == tar.TypeReg {
			h.Size = int64(len(data))
		}
		h.Mode = 0o644
		if err := tw.WriteHeader(h); err != nil {
			t.Fatal(err)
		}
		_, _ = io.WriteString(tw, data)
	}
	add(&tar.Header{Typeflag: tar.TypeDir, Name: "attachments/"}, "")
	add(&tar.Header{Typeflag: tar.TypeReg, Name: "attachments/fine.txt"}, "fine")
	add(&tar.Header{Typeflag: tar.TypeSymlink, Name: "attachments/etc", Linkname: "/etc"}, "")
	add(&tar.Header{Typeflag: tar.TypeReg, Name: "attachments/etc/pwned"}, "x")
	_ = tw.Close()
	_ = zw.Close()
	return buf.Bytes()
}

func restoreSafetyKVM(t *testing.T, ctx context.Context, s *savesEnv, session string) {
	b, _ := s.newVM(ctx, session)
	defer s.stop(ctx, b)
	s.run(b, "mkdir -p /workspace/sessions/"+session+"/attachments && echo keep > /workspace/sessions/"+session+"/attachments/marker")
	evil := evilArchive(t)
	sum := sha256.Sum256(evil)
	sha := hex.EncodeToString(sum[:])
	key := "eng-4572/evil-" + sha[:12]
	f, err := os.CreateTemp("", "evil")
	if err != nil {
		t.Fatal(err)
	}
	_, _ = f.Write(evil)
	_ = f.Close()
	defer func() { _ = os.Remove(f.Name()) }()
	// Upload with the presigned PUT, as a capture would.
	req := presign(t, "put", s.bucket, key, fmt.Sprint(len(evil)), sha)
	args := []string{"-sS", "-o", "/dev/null", "-w", "%{http_code}", "-X", "PUT", "--data-binary", "@" + f.Name()}
	for k, v := range req.GetHeaders() {
		args = append(args, "-H", k+": "+v)
	}
	out, err := exec.Command("curl", append(args, req.GetUrl())...).CombinedOutput()
	if err != nil || string(out) != "200" {
		t.Fatalf("put evil: %v %s", err, out)
	}
	_, err = s.restore(ctx, b, session, key, int64(len(evil)), sha)
	d, r := errDomainReason(err)
	t.Logf("evil archive (symlink /etc + file through it): %s/%s", d, r)
	if r != "ARCHIVE_INVALID" {
		t.Errorf("evil archive: %v", err)
	}
	_, err = s.restore(ctx, b, session, key, int64(len(evil)), strings.Repeat("0", 64))
	t.Logf("wrong sha256: %s", apierr.FromStatus(err))
	if apierr.FromStatus(err) != pb.ErrorReason_ARCHIVE_MISMATCH {
		t.Errorf("wrong sha: %v", err)
	}
	if out := s.run(b, "cat /workspace/sessions/"+session+"/attachments/marker; ls /etc/pwned 2>&1 | head -1; ls -A /workspace/sessions/"+session); !strings.HasPrefix(out, "keep") ||
		!strings.Contains(out, "No such file") || strings.Contains(out, ".craft-") {
		t.Errorf("guest after refused restores: %q", out)
	}
}

func errDomainReason(err error) (string, string) {
	for _, d := range status.Convert(err).Details() {
		if info, ok := d.(*errdetails.ErrorInfo); ok {
			return info.GetDomain(), info.GetReason()
		}
	}
	return "", ""
}

// guestBenchKVM copies a benchmark program into the guest with WriteFile and
// runs it (KVM_GUEST_BENCH; diagnostics only).
func guestBenchKVM(t *testing.T, s *savesEnv, a *savesVM, session, bin string) {
	raw, err := os.ReadFile(bin)
	if err != nil {
		t.Fatal(err)
	}
	ws, err := s.sd.WriteFile(a.ctx)
	if err != nil {
		t.Fatal(err)
	}
	_ = ws.Send(&sdpb.WriteFileRequest{Part: &sdpb.WriteFileRequest_Header{Header: &sdpb.WriteFileHeader{
		SessionId: session, Path: "bench/gobench", Size: int64(len(raw)), Mode: 0o755, MakeParents: true, Overwrite: true}}})
	for off := 0; off < len(raw); off += 1 << 20 {
		_ = ws.Send(&sdpb.WriteFileRequest{Part: &sdpb.WriteFileRequest_Data{Data: raw[off:min(off+1<<20, len(raw))]}})
	}
	if _, err := ws.CloseAndRecv(); err != nil {
		t.Fatal(err)
	}
	out := s.run(a, "/workspace/sessions/"+session+"/bench/gobench; rm -rf /workspace/sessions/"+session+"/bench")
	t.Logf("guest bench: %s", strings.ReplaceAll(out, "\n", " | "))
}
