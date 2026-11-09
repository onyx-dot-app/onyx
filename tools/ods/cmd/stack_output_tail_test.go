package cmd

import (
	"strings"
	"testing"
)

func TestCommandOutputTailRetainsBoundedSuffix(t *testing.T) {
	var output commandOutputTail
	var all strings.Builder
	for _, chunk := range []string{strings.Repeat("a", 1000), strings.Repeat("b", 100000), "\nfinal diagnostic\n"} {
		all.WriteString(chunk)
		if n, err := output.Write([]byte(chunk)); n != len(chunk) || err != nil {
			t.Fatalf("write returned %d, %v", n, err)
		}
		if len(output.data) > 64*1024 {
			t.Fatal("diagnostic buffer exceeded its byte limit")
		}
	}
	want := all.String()[all.Len()-64*1024:]
	if string(output.data) != want {
		t.Fatal("diagnostic buffer did not preserve the final bytes")
	}
}
