package main

import (
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

func TestReportVMs(t *testing.T) {
	started := time.Date(2026, 11, 10, 12, 0, 0, 0, time.FixedZone("x", 3600))
	got := reportVMs([]agent.VM{
		{SandboxID: "a", TenantID: "public", Attempt: 2, Generation: 7, State: pb.VMState_VM_STATE_RUNNING, Template: "t",
			VCPUs: 2, MemMiB: 4096, ScratchGiB: 4, PID: 9, StartedAt: started},
		{SandboxID: "b", State: pb.VMState_VM_STATE_EXITED},
	})
	if len(got) != 2 || got[0].State != "RUNNING" || got[1].State != "EXITED" ||
		got[0].Attempt != 2 || got[0].Generation != 7 || got[0].TenantID != "public" || got[0].PID != 9 {
		t.Fatalf("reportVMs %+v", got)
	}
	if got[0].StartedAt == nil || !got[0].StartedAt.Equal(started) || got[0].StartedAt.Location() != time.UTC {
		t.Fatalf("started_at %v", got[0].StartedAt)
	}
	if got[1].StartedAt != nil {
		t.Fatal("a zero start time must be omitted")
	}
}

func TestReportEnded(t *testing.T) {
	at := time.Date(2026, 11, 10, 12, 0, 0, 0, time.FixedZone("x", 3600))
	got := reportEnded([]agent.EndedVM{
		{SandboxID: "a", TenantID: "public", Attempt: 2, Generation: 7, Reason: agent.EndedExited, EndedAt: at},
	})
	if len(got) != 1 || got[0].Reason != "EXITED" || got[0].Attempt != 2 || got[0].Generation != 7 ||
		got[0].TenantID != "public" || !got[0].EndedAt.Equal(at) || got[0].EndedAt.Location() != time.UTC {
		t.Fatalf("reportEnded %+v", got)
	}
}
