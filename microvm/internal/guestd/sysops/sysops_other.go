//go:build !linux

package sysops

import "time"

// SetClock is Linux only.
func SetClock(time.Time) error { return ErrUnsupported }

// AddEntropy is Linux only.
func AddEntropy([]byte) (bool, error, error) { return false, nil, ErrUnsupported }

// GrowFS is Linux only.
func GrowFS(string, uint64) (uint64, uint64, error) { return 0, 0, ErrUnsupported }

// EnsureCgroup2 is Linux only.
func EnsureCgroup2(string) error { return ErrUnsupported }
