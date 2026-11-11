package agent

import (
	"context"
	"sync/atomic"
)

type admittedKey struct{}

// WithAdmission returns a context for Create and a function that reports
// whether that Create passed admission (or found the VM already placed), so
// metrics can tell a refusal from a start that failed later.
func WithAdmission(ctx context.Context) (context.Context, func() bool) {
	var b atomic.Bool
	return context.WithValue(ctx, admittedKey{}, &b), b.Load
}

func markAdmitted(ctx context.Context) {
	if b, ok := ctx.Value(admittedKey{}).(*atomic.Bool); ok {
		b.Store(true)
	}
}
