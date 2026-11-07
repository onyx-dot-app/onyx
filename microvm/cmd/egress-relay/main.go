// Command egress-relay is the in-guest egress proxy endpoint of a Craft
// micro-VM. It listens on 127.0.0.1:3128 and splices each connection to the
// host over vsock (CID 2, port 3128). SIGHUP resets every live connection.
// The VM init runs it as uid 65534, apart from the guest daemon.
package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"net"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/egressrelay"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/vsock"
)

// version is set with -ldflags "-X main.version=...".
var version = "dev"

func main() {
	listen := flag.String("listen", "127.0.0.1:3128", "TCP listen address")
	cid := flag.Uint("vsock-cid", 2, "upstream vsock CID (2 is the host)")
	port := flag.Uint("vsock-port", 3128, "upstream vsock port")
	upstream := flag.String("upstream", "", "use unix:<path> as the upstream instead of vsock (tests)")
	maxConns := flag.Int("max-conns", 256, "most live connections; more are reset at once")
	idle := flag.Duration("idle-timeout", 0, "close a connection after this long with no bytes; 0 for none, else at least 180s")
	flag.Parse()
	if *maxConns <= 0 {
		fmt.Fprintln(os.Stderr, "-max-conns must be at least 1")
		os.Exit(2)
	}
	if *upstream != "" && (!strings.HasPrefix(*upstream, "unix:") || *upstream == "unix:") {
		fmt.Fprintf(os.Stderr, "-upstream must be unix:<path>, got %q\n", *upstream)
		os.Exit(2)
	}

	log := slog.New(slog.NewTextHandler(os.Stderr, nil))
	raiseNoFile(log)

	dial := func(ctx context.Context) (net.Conn, error) { return vsock.Dial(ctx, uint32(*cid), uint32(*port)) }
	target := fmt.Sprintf("vsock %d:%d", *cid, *port)
	if path, ok := strings.CutPrefix(*upstream, "unix:"); ok {
		dial = func(ctx context.Context) (net.Conn, error) {
			var d net.Dialer
			return d.DialContext(ctx, "unix", path)
		}
		target = *upstream
	}
	r := &egressrelay.Relay{Dial: dial, MaxConns: *maxConns, IdleTimeout: *idle, DialTimeout: 10 * time.Second, Log: log}
	if err := r.Validate(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	ln, err := net.Listen("tcp", *listen)
	if err != nil {
		log.Error("listen", "err", err)
		os.Exit(1)
	}

	sig := make(chan os.Signal, 4)
	signal.Notify(sig, syscall.SIGHUP, syscall.SIGTERM, syscall.SIGINT)
	go func() {
		for s := range sig {
			if s == syscall.SIGHUP {
				log.Info("SIGHUP: reset connections", "closed", r.Reset())
				continue
			}
			log.Info("stopping", "signal", s.String())
			_ = ln.Close()
			return
		}
	}()
	log.Info("egress-relay listening", "version", version, "listen", *listen, "upstream", target, "max_conns", *maxConns)
	if err := r.Serve(ln); err != nil {
		log.Error("serve", "err", err)
		os.Exit(1)
	}
	r.Reset()
}

// raiseNoFile sets the soft open-file limit to the hard limit.
func raiseNoFile(log *slog.Logger) {
	var lim syscall.Rlimit
	if err := syscall.Getrlimit(syscall.RLIMIT_NOFILE, &lim); err != nil {
		return
	}
	lim.Cur = lim.Max
	if err := syscall.Setrlimit(syscall.RLIMIT_NOFILE, &lim); err != nil {
		log.Warn("raise RLIMIT_NOFILE", "err", err)
	}
}
