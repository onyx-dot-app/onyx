//go:build !windows

package devstack

import (
	"context"
	"errors"
	"strings"
	"testing"
)

type migrationSafetyProvider struct {
	*fakeProvider
	pending  bool
	probeErr error
	previous []ServiceRecord
}

func (p *migrationSafetyProvider) MigrationsPending(context.Context, []string) (bool, error) {
	return p.pending, p.probeErr
}

func (p *migrationSafetyProvider) Migrate(ctx context.Context, env []string) error {
	for _, rec := range p.previous {
		if isCurrent(rec) {
			return errors.New("managed service still running during migration")
		}
	}
	return p.fakeProvider.Migrate(ctx, env)
}

func TestMigrationSafety(t *testing.T) {
	for _, test := range []struct {
		name     string
		pending  bool
		probeErr error
	}{
		{name: "pending stops services before upgrade", pending: true},
		{name: "head preserves service PIDs"},
		{name: "failed probe never upgrades", probeErr: errors.New("database unreachable")},
	} {
		t.Run(test.name, func(t *testing.T) {
			s := newTestStack(t, t.TempDir())
			p := &migrationSafetyProvider{fakeProvider: &fakeProvider{services: []string{"api", "worker"}}, pending: true}
			if _, err := s.Up(context.Background(), p, testOptions()); err != nil {
				t.Fatal(err)
			}
			before, err := s.ReadState()
			if err != nil {
				t.Fatal(err)
			}
			p.previous = append([]ServiceRecord(nil), before.Services...)
			p.pending, p.probeErr = test.pending, test.probeErr
			_, err = s.Up(context.Background(), p, testOptions())
			if test.probeErr != nil {
				if err == nil || !strings.Contains(err.Error(), test.probeErr.Error()) {
					t.Fatalf("probe failure was hidden: %v", err)
				}
			} else if err != nil {
				t.Fatal(err)
			}
			wantMigrations := 1
			if test.pending {
				wantMigrations++
			}
			if len(p.migrated) != wantMigrations {
				t.Fatalf("migrations = %d, want %d", len(p.migrated), wantMigrations)
			}
			for _, previous := range p.previous {
				if live := isCurrent(previous); live == test.pending {
					t.Fatalf("old %s live = %v, pending = %v", previous.Slug, live, test.pending)
				}
			}
		})
	}
}
