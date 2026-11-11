package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"time"

	"google.golang.org/grpc"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestlog"
	"github.com/onyx-dot-app/onyx/microvm/internal/hostinfo"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	"github.com/onyx-dot-app/onyx/microvm/internal/metrics"
	"github.com/onyx-dot-app/onyx/microvm/internal/relay"
	"github.com/onyx-dot-app/onyx/microvm/internal/server"
)

// obsFlags are the metrics, audit and guest log flags (ENG-4570).
type obsFlags struct {
	metricsListen string
	metricsToken  string
	metricsNoAuth bool
	guestLogRate  int
	guestLogBurst int
	guestLogNode  int
	guestLogMax   int64
}

func (o *obsFlags) register(fs *flag.FlagSet) {
	fs.StringVar(&o.metricsListen, "metrics-listen", "", "plain HTTP address for Prometheus /metrics (for example :9464); empty: off")
	fs.StringVar(&o.metricsToken, "metrics-token-file", "", "file with the bearer token that /metrics requires (the Onyx METRICS_AUTH_TOKEN), read on each scrape; with no token every scrape gets 401")
	fs.BoolVar(&o.metricsNoAuth, "metrics-auth-disabled", false, "serve /metrics with no auth (like DISABLE_METRICS_AUTH)")
	fs.IntVar(&o.guestLogRate, "guest-log-rate", guestlog.DefaultVMRate, "bytes per second of serial console and Firecracker log shipped to stdout per VM; 0 turns shipping off")
	fs.IntVar(&o.guestLogBurst, "guest-log-burst", guestlog.DefaultVMBurst, "guest log burst per VM, in bytes")
	fs.IntVar(&o.guestLogNode, "guest-log-node-rate", guestlog.DefaultNodeRate, "guest log bytes per second for the whole node")
	fs.Int64Var(&o.guestLogMax, "guest-log-max-file-bytes", guestlog.DefaultMaxFileBytes, "cap of each VM's console.log and fc.log on the data disk, also with shipping off; 0: no cap")
}

func (o obsFlags) check() error {
	if o.guestLogRate < 0 || o.guestLogBurst < 1 || o.guestLogNode < 1 || o.guestLogMax < 0 {
		return errors.New("--guest-log-rate and --guest-log-max-file-bytes must be 0 or more, --guest-log-burst and --guest-log-node-rate 1 or more")
	}
	if o.metricsToken != "" && o.metricsNoAuth {
		return errors.New("--metrics-token-file and --metrics-auth-disabled exclude each other")
	}
	if o.metricsListen != "" {
		if _, _, err := net.SplitHostPort(o.metricsListen); err != nil {
			return fmt.Errorf("--metrics-listen %q: %w", o.metricsListen, err)
		}
	}
	return nil
}

// observability holds the metrics, the audit interceptor and the guest log
// shipper.
type observability struct {
	f        obsFlags
	log      *slog.Logger
	metrics  *metrics.Metrics
	observer *server.Observer
	shipper  *guestlog.Shipper
	dials    func() int
}

// newObservability wires the metrics into the Manager and the relay. Call it
// after setupEgress and before Recover, so it sees every VM.
func newObservability(f obsFlags, m *agent.Manager, lay jailer.Layout, stats agent.HostStats, log *slog.Logger) (*observability, error) {
	if err := f.check(); err != nil {
		return nil, err
	}
	o := &observability{f: f, log: log}
	src := metrics.Source{VMs: m.List, Stats: stats, PrivateMem: hostinfo.PrivateMemoryBytes, DialStreams: func() int {
		if o.dials == nil {
			return 0
		}
		return o.dials()
	}}
	var rl *relay.Relay
	if ae, ok := m.Egress().(*relay.AgentEgress); ok {
		rl = ae.Relay
		src.RelayConns = rl.Open
	}
	mt, err := metrics.New(src)
	if err != nil {
		return nil, err
	}
	o.metrics = mt
	if rl != nil {
		rl.Events = mt.RelayEvent
	}
	o.observer = &server.Observer{Log: log, Metrics: mt, Tenant: m.Tenant}
	if f.guestLogRate > 0 || f.guestLogMax > 0 {
		o.shipper = &guestlog.Shipper{
			Layout: lay, VMs: m.List,
			Out:    slog.New(slog.NewJSONHandler(os.Stdout, nil)),
			VMRate: f.guestLogRate, VMBurst: f.guestLogBurst, NodeRate: f.guestLogNode,
			Count: mt.GuestLog, MaxFileBytes: f.guestLogMax, ShipOff: f.guestLogRate == 0,
		}
		m.OnRelease(o.shipper.Release)
	}
	return o, nil
}

func (o *observability) serverOptions() []grpc.ServerOption { return o.observer.ServerOptions() }

// start starts the guest log shipper and the metrics listener. Call it after
// Recover and before the API serves.
func (o *observability) start(ctx context.Context, svc *server.Service) error {
	o.dials = svc.OpenDials
	if o.shipper != nil {
		o.shipper.Start(ctx)
	}
	if o.f.metricsListen == "" {
		return nil
	}
	ln, err := net.Listen("tcp", o.f.metricsListen)
	if err != nil {
		return fmt.Errorf("--metrics-listen: %w", err)
	}
	if !o.f.metricsNoAuth && o.f.metricsToken == "" {
		o.log.Warn("/metrics has no token: every scrape gets 401; set --metrics-token-file or --metrics-auth-disabled")
	}
	srv := o.metrics.Server(o.f.metricsListen, metrics.BearerAuth{TokenFile: o.f.metricsToken, Disabled: o.f.metricsNoAuth})
	go func() {
		if err := srv.Serve(ln); err != nil && !errors.Is(err, http.ErrServerClosed) {
			o.log.Error("metrics listener", "err", err)
		}
	}()
	go func() {
		<-ctx.Done()
		sctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = srv.Shutdown(sctx)
	}()
	return nil
}
