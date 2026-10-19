//go:build !windows

package devstack

import (
	"fmt"
	"testing"
)

type modelEnvProvider struct {
	*fakeProvider
}

func (p *modelEnvProvider) InfraEnv(ports map[string]int) map[string]string {
	values := p.fakeProvider.InfraEnv(ports)
	values["MODEL_SERVER_PORT"] = fmt.Sprint(ports["MODEL_SERVER_HOST_PORT"])
	return values
}

func TestModelServerModeUsesActivePortAndRetainsLocalAssignment(t *testing.T) {
	stack := newTestStack(t, t.TempDir())
	provider := &modelEnvProvider{fakeProvider: &fakeProvider{}}
	state := &State{Ports: map[string]int{"model": 19001, "MODEL_SERVER_HOST_PORT": 19002}}
	if err := stack.WriteState(state); err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name  string
		local bool
		want  string
	}{
		{"initial local mode", true, "19001"},
		{"switch to Docker mode", false, "19002"},
		{"switch back to local mode", true, "19001"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			env, fileEnv, err := stack.serviceEnv(provider, state.Ports, Options{LocalModelServer: tc.local})
			if err != nil {
				t.Fatal(err)
			}
			if got := EnvValue(env.With(fileEnv), "MODEL_SERVER_PORT"); got != tc.want {
				t.Fatalf("active model port = %s, want %s", got, tc.want)
			}
			if state.Ports["model"] != 19001 {
				t.Fatal("mode transition discarded durable local model assignment")
			}
			persisted, err := stack.ReadState()
			if err != nil {
				t.Fatal(err)
			}
			if persisted.Ports["model"] != 19001 {
				t.Fatal("persisted local model assignment changed")
			}
		})
	}
}
