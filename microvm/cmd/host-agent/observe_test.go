package main

import "testing"

func TestObsFlagsCheck(t *testing.T) {
	ok := obsFlags{guestLogRate: 1, guestLogBurst: 1, guestLogNode: 1}
	for name, tc := range map[string]struct {
		f     obsFlags
		valid bool
	}{
		"defaults off":     {ok, true},
		"metrics":          {obsFlags{metricsListen: ":9464", guestLogRate: 1, guestLogBurst: 1, guestLogNode: 1}, true},
		"shipping off":     {obsFlags{guestLogBurst: 1, guestLogNode: 1}, true},
		"bad address":      {obsFlags{metricsListen: "9464", guestLogRate: 1, guestLogBurst: 1, guestLogNode: 1}, false},
		"negative rate":    {obsFlags{guestLogRate: -1, guestLogBurst: 1, guestLogNode: 1}, false},
		"zero node budget": {obsFlags{guestLogRate: 1, guestLogBurst: 1}, false},
	} {
		if err := tc.f.check(); (err == nil) != tc.valid {
			t.Errorf("%s: %v", name, err)
		}
	}
}
