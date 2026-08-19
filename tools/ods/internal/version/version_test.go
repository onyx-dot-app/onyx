package version

import "testing"

func TestNormalize(t *testing.T) {
	cases := map[string]string{
		"v6.0.2":  "6.0.2",
		"V6.0.2":  "6.0.2",
		"6.0.2":   "6.0.2",
		"  v41  ": "41",
		"main":    "main",
		"":        "",
		"v":       "v", // too short to strip
	}
	for in, want := range cases {
		if got := Normalize(in); got != want {
			t.Errorf("Normalize(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestIsSemverish(t *testing.T) {
	if !IsSemverish("v45.0.7") || !IsSemverish("41") {
		t.Error("v45.0.7 and 41 should be semverish")
	}
	if IsSemverish("main") || IsSemverish("") {
		t.Error("branch names and empty strings are not semverish")
	}
}

func TestCompare(t *testing.T) {
	cases := []struct {
		a, b string
		want int
	}{
		{"46.0.1", "46.0.0", 1},
		{"46.0.0", "46.0.1", -1},
		{"v46.0.1", "46.0.1", 0}, // v-prefix normalized before compare
		{"41", "40.9.9", 1},
	}
	for _, tc := range cases {
		if got := Compare(tc.a, tc.b); got != tc.want {
			t.Errorf("Compare(%q, %q) = %d, want %d", tc.a, tc.b, got, tc.want)
		}
	}
}
