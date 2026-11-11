//go:build kvm && linux

package kvmtest

import (
	"context"
	"errors"
	"testing"

	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

type interruptedExecStream struct {
	events []*pb.ExecEvent
	next   int
}

func (s *interruptedExecStream) Recv() (*pb.ExecEvent, error) {
	if s.next == len(s.events) {
		return nil, context.DeadlineExceeded
	}
	event := s.events[s.next]
	s.next++
	return event, nil
}

func TestCollectKeepsPartialOutput(t *testing.T) {
	stream := &interruptedExecStream{events: []*pb.ExecEvent{
		{Event: &pb.ExecEvent_Started{Started: &pb.ExecStarted{ExecutionId: "interrupted-command"}}},
		{Event: &pb.ExecEvent_Output{Output: &pb.OutputChunk{Stream: pb.OutputStream_STDOUT, Data: []byte("partial output\n")}}},
		{Event: &pb.ExecEvent_Output{Output: &pb.OutputChunk{Stream: pb.OutputStream_STDERR, Data: []byte("partial error\n")}}},
	}}
	result, err := collect(stream)
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("error = %v", err)
	}
	if result.id != "interrupted-command" || result.stdout != "partial output\n" || result.stderr != "partial error\n" {
		t.Fatalf("lost interrupted execution output: %+v", result)
	}
	if result.res != nil {
		t.Fatal("interrupted execution must not have a completion result")
	}
}
