// Package kvmtest holds the KVM integration tests of the host agent. They
// need a KVM host and run only with the build tag "kvm":
//
//	go test -c -tags kvm -o hostagent-kvm.test ./internal/kvmtest
//	sudo ./hostagent-kvm.test -test.v
//
// See the module README for the host setup and the environment variables.
package kvmtest
