package devstack

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// The caller holds the checkout lock and has stopped its own web services.
func (s *Stack) clearNextDevCache() error {
	otherMode := Shared
	if s.Mode == Shared {
		otherMode = Isolated
	}
	other, err := Open(s.Root, "", otherMode)
	if err != nil {
		return err
	}
	st, err := other.ReadState()
	if err != nil {
		return err
	}
	if st != nil && st.Root == s.Root {
		for _, rec := range st.Services {
			if rec.Slug == "web" && isCurrent(rec) {
				return fmt.Errorf("cannot clear Next.js development cache while the %s stack runs web in this checkout", otherMode)
			}
		}
	}

	root, err := os.OpenRoot(s.Root)
	if err != nil {
		return fmt.Errorf("open worktree for Next.js cache cleanup: %w", err)
	}
	defer func() { _ = root.Close() }()
	if err := root.RemoveAll(filepath.Join("web", ".next", "dev")); err != nil {
		return fmt.Errorf("clear Next.js development cache: %w", err)
	}
	return nil
}

func (s *Stack) lockFrontendService(ctx context.Context, target Target, wait time.Duration) (func(), error) {
	source := &Stack{Root: target.Root, Project: target.Project, StateDir: target.StateDir, Mode: target.Mode}
	releaseSource, err := source.Lock(ctx, "frontend API lookup", wait)
	if err != nil {
		return nil, err
	}
	fail := func(err error) (func(), error) { releaseSource(); return nil, err }
	st, err := source.ReadState()
	if err != nil {
		return fail(err)
	}
	if st == nil || st.Project != target.Project {
		return fail(fmt.Errorf("no managed API for project %s; run 'ods stack up' or 'ods backend api' first", target.Project))
	}
	local, err := Open(s.Root, "", Isolated)
	if err != nil {
		return fail(err)
	}
	releaseLocal := func() {}
	if local.StateDir != source.StateDir {
		releaseLocal, err = local.Lock(ctx, "frontend checkout lookup", wait)
		if err != nil {
			return fail(err)
		}
	}
	release := func() { releaseLocal(); releaseSource() }
	localState, err := local.ReadState()
	if err != nil {
		release()
		return nil, err
	}
	for _, candidate := range []*State{st, localState} {
		if candidate == nil || candidate.Root != s.Root {
			continue
		}
		for _, rec := range candidate.Services {
			if rec.Slug == "web" && isCurrent(rec) {
				release()
				return nil, fmt.Errorf("a frontend already runs in this checkout at http://localhost:%d; reuse it", rec.Port)
			}
		}
	}
	for _, rec := range st.Services {
		if rec.Slug == "api" && rec.Port > 0 && isCurrent(rec) && rec.Health != "" && healthy(ctx, rec.Health) {
			target.Ports["api"] = rec.Port
			return release, nil
		}
	}
	release()
	return nil, fmt.Errorf("no healthy managed API in %s; run 'ods stack up' or 'ods backend api' there first", st.Root)
}

func (s *Stack) lockFrontendCheckout(ctx context.Context, wait time.Duration) (func(), error) {
	local, err := Open(s.Root, "", Isolated)
	if err != nil {
		return nil, err
	}
	if local.StateDir == s.StateDir {
		return func() {}, nil
	}
	return local.Lock(ctx, "full stack handoff", wait)
}

func (s *Stack) stopFrontendPreview(ctx context.Context, opts Options) (int, error) {
	preview, err := Open(s.Root, "", Frontend)
	if err != nil {
		return 0, err
	}
	release, err := preview.Lock(ctx, "full stack handoff", opts.LockWait)
	if err != nil {
		return 0, err
	}
	defer release()
	st, err := preview.ReadState()
	if err != nil || st == nil {
		return 0, err
	}
	if st.Root != s.Root {
		return 0, preview.ownerError(st)
	}
	port := 0
	for _, rec := range st.Services {
		if rec.Slug == "web" && isCurrent(rec) {
			port = rec.Port
		}
	}
	if err := preview.stopServices(opts.StopTimeout); err != nil {
		return 0, err
	}
	if s.Registry != nil {
		if err := s.Registry.Release(preview.StateDir); err != nil {
			return 0, err
		}
	}
	return port, nil
}
