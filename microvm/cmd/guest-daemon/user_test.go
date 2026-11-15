package main

import (
	"maps"
	"slices"
	"testing"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd"
)

func TestParseCommandUser(t *testing.T) {
	known := func(int) account {
		return account{name: "sandbox", home: "/home/sandbox", groups: []string{"1000", "27", "bad"}}
	}
	unknown := func(int) account { return account{} }

	if id, err := parseCommandUser("", known); err != nil || id != nil {
		t.Fatalf("empty: %v %v, want nil (root)", id, err)
	}
	for _, bad := range []string{"1000", "a:b", "1000:", "-1:0"} {
		if _, err := parseCommandUser(bad, known); err == nil {
			t.Errorf("%q: no error", bad)
		}
	}

	id, err := parseCommandUser("1000:1001", known)
	if err != nil {
		t.Fatal(err)
	}
	if c := id.cred; c.Uid != 1000 || c.Gid != 1001 || !slices.Equal(c.Groups, []uint32{1000, 27}) {
		t.Fatalf("credential %+v", c)
	}
	want := map[string]string{"HOME": "/home/sandbox", "USER": "sandbox", "LOGNAME": "sandbox"}
	if !maps.Equal(id.env, want) {
		t.Fatalf("env %v, want %v", id.env, want)
	}

	// No passwd entry: fallbacks and no supplementary groups.
	id, err = parseCommandUser("1000:1000", unknown)
	if err != nil {
		t.Fatal(err)
	}
	if id.cred.Groups == nil || len(id.cred.Groups) != 0 {
		t.Fatalf("groups %v, want an empty list", id.cred.Groups)
	}
	want = map[string]string{"HOME": "/home/onyx", "USER": "sandbox", "LOGNAME": "sandbox"}
	if !maps.Equal(id.env, want) {
		t.Fatalf("env %v, want %v", id.env, want)
	}
}

func TestBaseEnv(t *testing.T) {
	environ := []string{"HOME=/root", "USER=root", "HTTP_PROXY=http://127.0.0.1:3128"}
	root := baseEnv(environ, nil)
	if root["HOME"] != "/root" || root["USER"] != "root" || root["HTTP_PROXY"] == "" || root["PATH"] != guestd.DefaultBaseEnv["PATH"] {
		t.Fatalf("root env %v", root)
	}
	id, err := parseCommandUser("1000:1000", func(int) account { return account{name: "sandbox", home: "/home/sandbox"} })
	if err != nil {
		t.Fatal(err)
	}
	user := baseEnv(environ, id)
	if user["HOME"] != "/home/sandbox" || user["USER"] != "sandbox" || user["LOGNAME"] != "sandbox" || user["HTTP_PROXY"] == "" {
		t.Fatalf("user env %v", user)
	}
}
