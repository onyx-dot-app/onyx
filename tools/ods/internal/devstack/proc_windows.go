//go:build windows

package devstack

import (
	"os"
	"time"
)

func rememberGroup(*ServiceRecord) {}

func startService(Spec, string) (ServiceRecord, error) { return ServiceRecord{}, errUnsupported }

func launchService(Spec, string, ServiceIO) (ServiceRecord, <-chan error, error) {
	return ServiceRecord{}, nil, errUnsupported
}

func signalService(ServiceRecord, os.Signal) error { return errUnsupported }

func isCurrent(ServiceRecord) bool { return false }

func groupAlive(int) bool { return false }

func groupIsOurs(ServiceRecord) bool { return false }

func stopRecords(recs []ServiceRecord, _ time.Duration) []ServiceRecord { return nil }

func portHeldByGroup(int, int) bool { return false }
