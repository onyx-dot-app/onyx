// Package kvmtest holds the KVM tests of the guest daemon. They boot
// Firecracker VMs with the daemon in the root disk and call it over the VM
// vsock socket. They need a KVM host and run only with the build tag "kvm":
//
//	GOOS=linux GOARCH=amd64 go test -c -tags kvm -o guestd-kvm.test ./internal/guestd/kvmtest
//	sudo ./guestd-kvm.test -test.v
//
// Environment: KVM_FC_BIN (firecracker), KVM_IMG_DIR (vmlinux, the ENG-4574
// rootfs.ext4 with the daemon, scratch-empty.ext4, managed-empty.ext4),
// KVM_WORK_DIR, KVM_VMS (default 20), KVM_RESTORE_GAP (default 20s),
// KVM_BOOT_ARGS, KVM_TEMPLATE_ARGS, KVM_RELAY_BIN (egress-relay binary).
// KVM_RUNTIME_IMAGE=1 enables the tool smoke check for a craft-runtime rootfs.
package kvmtest
