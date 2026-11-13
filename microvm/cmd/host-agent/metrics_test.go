package main

import (
	"context"
	"crypto/ed25519"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/metrics"
	"github.com/onyx-dot-app/onyx/microvm/internal/nodereport"
	"github.com/onyx-dot-app/onyx/microvm/internal/relay"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	"github.com/onyx-dot-app/onyx/microvm/internal/tplbuild"
)

func TestTemplateResult(t *testing.T) {
	tpl := &template.Template{}
	for name, tc := range map[string]struct {
		r    tplbuild.Result
		err  error
		want string
	}{
		"built":               {tplbuild.Result{Template: tpl, Built: true}, nil, metrics.TemplateBuilt},
		"existing":            {tplbuild.Result{Template: tpl}, nil, metrics.TemplateExisting},
		"failed":              {tplbuild.Result{}, errors.New("boot"), metrics.TemplateFailed},
		"built, GC failed":    {tplbuild.Result{Template: tpl, Built: true}, errors.New("gc"), metrics.TemplateBuilt},
		"no template, no err": {tplbuild.Result{}, nil, metrics.TemplateFailed},
	} {
		if got := templateResult(tc.r, tc.err); got != tc.want {
			t.Errorf("%s: %s, want %s", name, got, tc.want)
		}
	}
}

func TestPushersWithoutEgressStartNothing(t *testing.T) {
	pushers{}.start(t.Context(), nil)
}

func TestPushersCountIntoMetrics(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {}))
	defer srv.Close()
	_, key, err := ed25519.GenerateKey(nil)
	if err != nil {
		t.Fatal(err)
	}
	signer := relay.NewSigner("node-a", "node-a-1", key)
	quiet := slog.New(slog.NewTextHandler(io.Discard, nil))
	g := &relay.Registrar{BaseURL: srv.URL, Secret: "s", Signer: signer, Log: quiet}
	r := &nodereport.Reporter{
		BaseURL: srv.URL, Signer: signer, List: func() []nodereport.VM { return nil },
		Ready: g.Registered(), Log: quiet, Interval: time.Hour,
	}
	mt, err := metrics.New(metrics.Source{})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(t.Context())
	defer cancel()
	pushers{reg: g, rep: r}.start(ctx, mt)
	deadline := time.Now().Add(5 * time.Second)
	for {
		reg := counter(t, mt, "craft_fc_host_agent_key_registrations_total", "success")
		rep := counter(t, mt, "craft_fc_host_agent_node_reports_total", "success")
		if reg == 1 && rep == 1 {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("key registrations %v, node reports %v", reg, rep)
		}
		<-time.After(time.Millisecond)
	}
}

func counter(t *testing.T, mt *metrics.Metrics, name, result string) float64 {
	t.Helper()
	fams, err := mt.Registry().Gather()
	if err != nil {
		t.Fatal(err)
	}
	for _, f := range fams {
		if f.GetName() != name {
			continue
		}
		for _, m := range f.GetMetric() {
			for _, l := range m.GetLabel() {
				if l.GetName() == "result" && l.GetValue() == result {
					return m.GetCounter().GetValue()
				}
			}
		}
	}
	return 0
}
