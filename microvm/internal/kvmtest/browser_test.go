//go:build kvm && linux

package kvmtest

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
	sdpb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

const brCDPPort = 9222

// dialConn is a node agent Dial stream as an io.ReadWriteCloser: what the
// api_server uses to reach the guest's CDP port.
type dialConn struct {
	s      pb.HostAgent_DialClient
	cancel context.CancelFunc
	first  *pb.DialFrame
	buf    []byte
}

func openDial(ctx context.Context, ha pb.HostAgentClient, sandboxID string, port uint32) (*dialConn, error) {
	ctx, cancel := context.WithCancel(ctx)
	s, err := ha.Dial(ctx)
	if err != nil {
		cancel()
		return nil, err
	}
	return &dialConn{s: s, cancel: cancel, first: &pb.DialFrame{SandboxId: sandboxID, GuestPort: port}}, nil
}

func (d *dialConn) Write(p []byte) (int, error) {
	f := &pb.DialFrame{Data: append([]byte(nil), p...)}
	if d.first != nil {
		f, d.first = d.first, nil
		f.Data = append([]byte(nil), p...)
	}
	if err := d.s.Send(f); err != nil {
		return 0, err
	}
	return len(p), nil
}

func (d *dialConn) Read(p []byte) (int, error) {
	for len(d.buf) == 0 {
		f, err := d.s.Recv()
		if err != nil {
			return 0, err
		}
		d.buf = f.GetData()
	}
	n := copy(p, d.buf)
	d.buf = d.buf[n:]
	return n, nil
}

// Close ends the stream; the agent then closes the guest connection.
func (d *dialConn) Close() error {
	d.cancel()
	return nil
}

// cdpHTTP sends one HTTP GET to the CDP port through Dial.
func cdpHTTP(ctx context.Context, ha pb.HostAgentClient, id, path string) (string, error) {
	c, err := openDial(ctx, ha, id, brCDPPort)
	if err != nil {
		return "", err
	}
	defer func() { _ = c.Close() }()
	if _, err := fmt.Fprintf(c, "GET %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nConnection: close\r\n\r\n", path, brCDPPort); err != nil {
		return "", err
	}
	resp, err := http.ReadResponse(bufio.NewReader(c), nil)
	if err != nil {
		return "", err
	}
	defer func() { _ = resp.Body.Close() }()
	b, err := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return string(b), fmt.Errorf("HTTP %d", resp.StatusCode)
	}
	return string(b), err
}

// cdp is a minimal CDP client: WebSocket (RFC 6455, client frames masked,
// no Origin header) over a Dial stream.
type cdp struct {
	c  *dialConn
	r  *bufio.Reader
	id int
}

func dialCDP(ctx context.Context, ha pb.HostAgentClient, id, path string) (*cdp, error) {
	c, err := openDial(ctx, ha, id, brCDPPort)
	if err != nil {
		return nil, err
	}
	key := make([]byte, 16)
	_, _ = rand.Read(key)
	if _, err := fmt.Fprintf(c, "GET %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"+
		"Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n", path, brCDPPort, base64.StdEncoding.EncodeToString(key)); err != nil {
		return nil, err
	}
	r := bufio.NewReaderSize(c, 1<<16)
	resp, err := http.ReadResponse(r, nil)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusSwitchingProtocols {
		return nil, fmt.Errorf("websocket upgrade: HTTP %d", resp.StatusCode)
	}
	return &cdp{c: c, r: r}, nil
}

func (w *cdp) writeText(p []byte) error {
	var h []byte
	h = append(h, 0x81)
	switch n := len(p); {
	case n < 126:
		h = append(h, 0x80|byte(n))
	case n < 1<<16:
		h = append(h, 0x80|126, byte(n>>8), byte(n))
	default:
		h = append(h, 0x80|127)
		h = binary.BigEndian.AppendUint64(h, uint64(n))
	}
	mask := make([]byte, 4)
	_, _ = rand.Read(mask)
	h = append(h, mask...)
	body := make([]byte, len(p))
	for i := range p {
		body[i] = p[i] ^ mask[i%4]
	}
	_, err := w.c.Write(append(h, body...))
	return err
}

func (w *cdp) readMessage() ([]byte, error) {
	var msg []byte
	for {
		var hdr [2]byte
		if _, err := io.ReadFull(w.r, hdr[:]); err != nil {
			return nil, err
		}
		fin, op := hdr[0]&0x80 != 0, hdr[0]&0x0f
		n := uint64(hdr[1] & 0x7f)
		switch n {
		case 126:
			var b [2]byte
			if _, err := io.ReadFull(w.r, b[:]); err != nil {
				return nil, err
			}
			n = uint64(binary.BigEndian.Uint16(b[:]))
		case 127:
			var b [8]byte
			if _, err := io.ReadFull(w.r, b[:]); err != nil {
				return nil, err
			}
			n = binary.BigEndian.Uint64(b[:])
		}
		payload := make([]byte, n)
		if _, err := io.ReadFull(w.r, payload); err != nil {
			return nil, err
		}
		switch op {
		case 0x8:
			return nil, errors.New("websocket closed")
		case 0x9, 0xA:
			continue
		}
		msg = append(msg, payload...)
		if fin {
			return msg, nil
		}
	}
}

// call sends one CDP command and returns its result, skipping events.
func (w *cdp) call(method string, params any, session string) (json.RawMessage, error) {
	w.id++
	req := map[string]any{"id": w.id, "method": method}
	if params != nil {
		req["params"] = params
	}
	if session != "" {
		req["sessionId"] = session
	}
	raw, _ := json.Marshal(req)
	if err := w.writeText(raw); err != nil {
		return nil, err
	}
	for {
		m, err := w.readMessage()
		if err != nil {
			return nil, err
		}
		var resp struct {
			ID     int             `json:"id"`
			Result json.RawMessage `json:"result"`
			Error  *struct {
				Message string `json:"message"`
			} `json:"error"`
		}
		if err := json.Unmarshal(m, &resp); err != nil {
			return nil, err
		}
		if resp.ID != w.id {
			continue
		}
		if resp.Error != nil {
			return nil, fmt.Errorf("%s: %s", method, resp.Error.Message)
		}
		return resp.Result, nil
	}
}

func (w *cdp) close() { _ = w.c.Close() }

// startBrowserAgent runs the agent container with the CDP port on the Dial
// allow-list, mTLS, and no egress (the test pages are data: URLs).
func startBrowserAgent(t *testing.T, e env, name, certDir string, certs *testcerts.Set) {
	t.Helper()
	bin := getenv("KVM_AGENT_BIN", "/opt/agent/host-agent")
	image := getenv("KVM_AGENT_IMAGE", "debian:trixie-slim")
	args := []string{"run", "-d", "--name", name, "--privileged", "--pid=host", "--cgroupns=private", "--network=host",
		"-v", e.DataDir + ":" + e.DataDir, "-v", certDir + ":" + certDir + ":ro",
		"-v", e.ArtifactsDir + ":" + e.ArtifactsDir + ":ro", "-v", filepath.Dir(bin) + ":" + filepath.Dir(bin) + ":ro",
		image, bin, "--data-dir", e.DataDir, "--artifacts-dir", e.ArtifactsDir,
		"--listen", ptListen, "--tls-cert", certs.ServerCert, "--tls-key", certs.ServerKey, "--client-ca", certs.ClientCA,
		"--node-id", ptNodeID, "--dial-ports", fmt.Sprintf("3010,%d", brCDPPort)}
	if out, err := exec.Command("docker", args...).CombinedOutput(); err != nil {
		t.Fatalf("docker run: %v: %s", err, out)
	}
}

const brPage = `data:text/html,<html><body style="margin:0;background:%2300897b;color:white;font:64px sans-serif">` +
	`<h1 id="t">Craft ENG-4573</h1><p>headful Chromium on Xvfb</p></body></html>`

// pngSize reads the width and height from a PNG header.
func pngSize(b []byte) (int, int, error) {
	if len(b) < 24 || !bytes.Equal(b[:8], []byte("\x89PNG\r\n\x1a\n")) {
		return 0, 0, errors.New("not a PNG")
	}
	return int(binary.BigEndian.Uint32(b[16:20])), int(binary.BigEndian.Uint32(b[20:24])), nil
}

// TestBrowserKVM: headful Chromium in a VM, driven over CDP through node
// agent Dial (ENG-4573).
func TestBrowserKVM(t *testing.T) {
	e := loadEnv()
	e.Template = getenv("KVM_BR_TEMPLATE", "kvmtest-br-1")
	cmd := newCommand(t, e)
	buildTemplateWith(t, e, cmd, getenv("KVM_PT_BOOT_ARGS", ptBootArgs), waitDaemon)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Minute)
	defer cancel()
	logDir := getenv("KVM_LOG_DIR", "/var/log/bench")
	certDir := getenv("KVM_CERT_DIR", "/opt/br/certs")
	if err := os.MkdirAll(certDir, 0o700); err != nil {
		t.Fatal(err)
	}
	certs, err := testcerts.Write(certDir)
	if err != nil {
		t.Fatal(err)
	}
	_ = exec.Command("docker", "rm", "-f", "br-a1").Run()
	t.Cleanup(func() {
		_ = os.WriteFile(filepath.Join(logDir, "br-a1.log"), []byte(containerLogs("br-a1")), 0o644)
		_ = exec.Command("docker", "rm", "-f", "br-a1").Run()
	})
	startBrowserAgent(t, e, "br-a1", certDir, certs)
	conn := ptConn(t, ctx, certs, "br-a1")
	ha, sd := pb.NewHostAgentClient(conn), sdpb.NewSandboxdClient(conn)

	id, key := newUUID(), randKey()
	cr, err := ha.Create(ctx, &pb.CreateRequest{SandboxId: id, Attempt: 1, Template: e.Template,
		Vcpus: tplVCPUs, MemMib: tplMemMiB, ScratchGib: scratchGiB, TenantId: "public", SandboxdKey: key})
	if err != nil {
		t.Fatalf("create: %v\n%s", err, containerLogs("br-a1"))
	}
	vm := cr.GetVm()
	t.Cleanup(func() {
		cctx, ccancel := context.WithTimeout(context.Background(), time.Minute)
		defer ccancel()
		_, _ = ha.Stop(cctx, &pb.StopRequest{SandboxId: id, Attempt: 1, Generation: vm.GetGeneration()})
		killFirecracker(t, vm.GetPid())
	})
	vc := vmCtx(ctx, id, key)
	ent := make([]byte, 64)
	_, _ = rand.Read(ent)
	if _, err := sd.Init(vc, &sdpb.InitRequest{HostTime: timestamppb.Now(), Entropy: ent, SandboxId: id,
		Generation: vm.GetGeneration(), ScratchBytes: scratchGiB << 30}); err != nil {
		t.Fatalf("init: %v", err)
	}
	run := func(script string) string {
		t.Helper()
		r, err := ptRun(vc, sd, "bash", "-c", script)
		if err != nil {
			t.Fatalf("run %q: %v", script, err)
		}
		return strings.TrimSpace(r.stdout + r.stderr)
	}
	t.Logf("guest: %s", run(`ls -l /usr/bin/Xvfb /opt/chrome/chrome /usr/bin/chromium 2>&1; (/opt/chrome/chrome --version || /usr/bin/chromium --version) 2>&1; id sandbox; `+
		`cat /proc/sys/user/max_user_namespaces; fc-list 2>/dev/null | wc -l`))
	guestLog := func() string {
		lctx, lcancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer lcancel()
		r, _ := ptRun(vmCtx(lctx, id, key), sd, "bash", "-c", "tail -c 4000 /run/craft-fc/log/guest-daemon.log")
		return r.stdout
	}
	stop := func() (*sdpb.BrowserStopResponse, error) {
		sctx, scancel := context.WithTimeout(vc, 60*time.Second)
		defer scancel()
		r, err := sd.BrowserStop(sctx, &sdpb.BrowserStopRequest{})
		if err != nil {
			t.Logf("BrowserStop failed: %v; guest daemon log:\n%s", err, guestLog())
		}
		return r, err
	}
	memAvail := func() string { return run(`awk '/MemAvailable/{print int($2/1024)" MiB"}' /proc/meminfo`) }
	before := memAvail()

	// 1. Start: Xvfb + Chromium, CDP ready.
	t0 := time.Now()
	st, err := sd.BrowserStart(vc, &sdpb.BrowserStartRequest{})
	startRPC := time.Since(t0)
	if err != nil {
		t.Fatalf("browser start: %v\nguest logs: %s", err, run("tail -c 3000 /run/craft-fc/log/guest-daemon.log"))
	}
	s := st.GetStatus()
	t.Logf("BENCH browser_start_first rpc_ms=%.0f start_duration_ms=%.0f state=%s cdp_port=%d cdp_path=%s pid=%d",
		msOf(startRPC), msOf(s.GetStartDuration().AsDuration()), s.GetState(), s.GetCdpPort(), s.GetCdpPath(), s.GetPid())
	if s.GetState() != sdpb.BrowserState_BROWSER_RUNNING || s.GetCdpPort() != brCDPPort || !strings.HasPrefix(s.GetCdpPath(), "/devtools/browser/") {
		t.Fatalf("status %v", s)
	}

	// 2. CDP over Dial: version (headful UA), the sandbox, a screenshot.
	ver, err := cdpHTTP(ctx, ha, id, "/json/version")
	if err != nil {
		t.Fatalf("json/version through Dial: %v %q", err, ver)
	}
	t.Logf("json/version: %s", strings.Join(strings.Fields(ver), " "))
	if strings.Contains(ver, "HeadlessChrome") || !strings.Contains(ver, "Chrome/") {
		t.Errorf("not a headful Chrome: %s", ver)
	}
	w, err := dialCDP(ctx, ha, id, s.GetCdpPath())
	if err != nil {
		t.Fatalf("cdp websocket: %v", err)
	}
	t1 := time.Now()
	res, err := w.call("Target.createTarget", map[string]any{"url": brPage}, "")
	if err != nil {
		t.Fatal(err)
	}
	var tgt struct {
		TargetID string `json:"targetId"`
	}
	_ = json.Unmarshal(res, &tgt)
	res, err = w.call("Target.attachToTarget", map[string]any{"targetId": tgt.TargetID, "flatten": true}, "")
	if err != nil {
		t.Fatal(err)
	}
	var att struct {
		SessionID string `json:"sessionId"`
	}
	_ = json.Unmarshal(res, &att)
	ready := ""
	for i := 0; i < 100 && ready != "complete"; i++ {
		res, err = w.call("Runtime.evaluate", map[string]any{"expression": "document.readyState", "returnByValue": true}, att.SessionID)
		if err != nil {
			t.Fatal(err)
		}
		var ev struct {
			Result struct {
				Value string `json:"value"`
			} `json:"result"`
		}
		_ = json.Unmarshal(res, &ev)
		ready = ev.Result.Value
	}
	res, err = w.call("Page.captureScreenshot", map[string]any{"format": "png"}, att.SessionID)
	if err != nil {
		t.Fatal(err)
	}
	var shot struct {
		Data string `json:"data"`
	}
	_ = json.Unmarshal(res, &shot)
	png, err := base64.StdEncoding.DecodeString(shot.Data)
	if err != nil {
		t.Fatal(err)
	}
	pw, ph, err := pngSize(png)
	if err != nil {
		t.Fatal(err)
	}
	_ = os.WriteFile(filepath.Join(logDir, "browser-shot.png"), png, 0o644)
	t.Logf("BENCH screenshot_ms=%.0f (new tab + load + capture) png=%dx%d bytes=%d", msOf(time.Since(t1)), pw, ph, len(png))
	if pw < 800 || ph < 400 {
		t.Errorf("screenshot %dx%d", pw, ph)
	}

	sandbox := run(`for p in $(pgrep -x 'chrome|chromium'); do grep -qa -- '--type=renderer' /proc/$p/cmdline || continue; ` +
		`echo "renderer $p uid=$(awk '/^Uid/{print $2}' /proc/$p/status) seccomp=$(awk '/^Seccomp:/{print $2}' /proc/$p/status)` +
		` userns_differs=$([ "$(readlink /proc/$p/ns/user)" != "$(readlink /proc/1/ns/user)" ] && echo yes || echo no)"; break; done; ` +
		`echo "no_sandbox_flags=$(for p in $(pgrep -x 'chrome|chromium'); do tr '\0' ' ' </proc/$p/cmdline; echo; done | grep -c -- --no-sandbox)"; ` +
		`ps -o user=,rss=,args= -C Xvfb | cut -c1-80`)
	t.Logf("sandbox check: %s", strings.ReplaceAll(sandbox, "\n", " | "))
	if !strings.Contains(sandbox, "seccomp=2") || !strings.Contains(sandbox, "userns_differs=yes") || !strings.Contains(sandbox, "no_sandbox_flags=0") {
		t.Errorf("Chromium sandbox not on: %s", sandbox)
	}

	// A persistent cookie: the profile test below reads it back.
	exp := float64(time.Now().Add(30 * 24 * time.Hour).Unix())
	if _, err := w.call("Storage.setCookies", map[string]any{"cookies": []map[string]any{{
		"name": "craft_eng_4573", "value": "kept", "domain": "example.com", "path": "/", "expires": exp,
	}}}, ""); err != nil {
		t.Fatal(err)
	}
	res, err = w.call("Storage.getCookies", nil, "")
	t.Logf("cookie before stop: found=%v", strings.Contains(string(res), `"value":"kept"`))
	w.close()
	bs, _ := sd.BrowserStatus(vc, &sdpb.BrowserStatusRequest{})
	t.Logf("BENCH browser_memory cgroup_mib=%.0f max_mib=%.0f guest_mem_available before=%s after=%s",
		float64(bs.GetStatus().GetMemoryBytes())/(1<<20), float64(bs.GetStatus().GetMemoryMaxBytes())/(1<<20), before, memAvail())
	t.Logf("browser cgroup: %s", strings.ReplaceAll(run(`cd /sys/fs/cgroup/guestd-browser && echo max=$(cat memory.max) oom_group=$(cat memory.oom.group) peak=$(cat memory.peak 2>/dev/null) && ls -d */`), "\n", " "))
	if bs.GetStatus().GetMemoryMaxBytes() != 2<<30 || bs.GetStatus().GetMemoryBytes() == 0 {
		t.Errorf("memory status %v", bs.GetStatus())
	}

	// 3. Stop saves the profile; a new start reads the cookie back.
	t2 := time.Now()
	sr, err := stop()
	if err != nil || !sr.GetClean() || !sr.GetProfileSaved() {
		t.Fatalf("stop: %v %v", sr, err)
	}
	t.Logf("BENCH browser_stop_ms=%.0f clean=%v profile_saved=%v profile_bytes=%d dir=%s", msOf(time.Since(t2)), sr.GetClean(),
		sr.GetProfileSaved(), sr.GetProfileBytes(), sr.GetProfileDir())
	t.Logf("cookies db: %s", strings.ReplaceAll(run(`for d in /workspace/.craft/browser-profile /var/lib/craft-browser/live; do `+
		`echo "$d: $(ls -l $d/Default/Cookies* | awk '{print $5, $9}' | tr '\n' ' ')"; `+
		`python3 -c "import sqlite3,sys; c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True); print(c.execute('select host_key,name from cookies').fetchall())" $d/Default/Cookies 2>&1 | tail -1; done`), "\n", " | "))
	t.Logf("saved profile: %s", strings.ReplaceAll(run(`du -sh /workspace/.craft/browser-profile; ls /workspace/.craft/browser-profile/Default | head -40 | tr '\n' ' '; `+
		`echo; ls -d /workspace/.craft/browser-profile/Default/Cache 2>&1; echo procs=$(pgrep -x 'chrome|chromium|Xvfb' | wc -l)`), "\n", " | "))
	if _, err := cdpHTTP(ctx, ha, id, "/json/version"); err == nil {
		t.Errorf("CDP port answers after stop")
	}

	var starts []float64
	for i := 0; i < 5; i++ {
		t0 := time.Now()
		st, err := sd.BrowserStart(vc, &sdpb.BrowserStartRequest{})
		if err != nil {
			t.Fatalf("restart %d: %v", i, err)
		}
		starts = append(starts, msOf(time.Since(t0)))
		if i == 0 {
			w, err := dialCDP(ctx, ha, id, st.GetStatus().GetCdpPath())
			if err != nil {
				t.Fatal(err)
			}
			res, err := w.call("Storage.getCookies", nil, "")
			w.close()
			if err != nil {
				t.Fatal(err)
			}
			t.Logf("cookie after stop/start: found=%v", strings.Contains(string(res), `"craft_eng_4573"`))
			if !strings.Contains(string(res), `"value":"kept"`) {
				t.Errorf("profile did not survive stop/start: %s", res)
			}
		}
		if _, err := stop(); err != nil {
			t.Fatal(err)
		}
	}
	t.Logf("BENCH browser_start_warm_ms n=5 p50=%.0f p95=%.0f max=%.0f", pctl(starts, 0.5), pctl(starts, 0.95), pctl(starts, 1))

	// 4. Crash: kill -9 of Chromium restarts it with a backoff.
	st, err = sd.BrowserStart(vc, &sdpb.BrowserStartRequest{})
	if err != nil {
		t.Fatal(err)
	}
	oldPID := st.GetStatus().GetPid()
	tk := time.Now()
	run(fmt.Sprintf("kill -9 %d", oldPID))
	var after *sdpb.BrowserStatus
	for time.Since(tk) < 30*time.Second {
		r, err := sd.BrowserStatus(vc, &sdpb.BrowserStatusRequest{})
		if err == nil && r.GetStatus().GetRestarts() == 1 && r.GetStatus().GetState() == sdpb.BrowserState_BROWSER_RUNNING {
			after = r.GetStatus()
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
	if after == nil {
		t.Fatalf("no restart after kill -9")
	}
	t.Logf("BENCH crash_restart_ms=%.0f (1 s backoff + start) new_pid=%d last_error=%.120q", msOf(time.Since(tk)), after.GetPid(), after.GetLastError())
	if v, err := cdpHTTP(ctx, ha, id, "/json/version"); err != nil {
		t.Errorf("CDP after restart: %v %q", err, v)
	}
	sr, err = stop()
	if err != nil || !sr.GetClean() {
		t.Errorf("stop after restart: %v %v", sr, err)
	}
	t.Logf("processes left after stop: %s; cgroups: %s", run(`pgrep -x 'chrome|chromium|Xvfb' | wc -l`),
		run(`ls -d /sys/fs/cgroup/guestd-browser/*/ 2>/dev/null | wc -l`))
}
