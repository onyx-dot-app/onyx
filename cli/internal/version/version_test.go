package version

import "testing"

func TestParse_Valid(t *testing.T) {
	tests := []struct {
		input string
		want  Semver
	}{
		{"3.1.2", Semver{3, 1, 2}},
		{"v3.1.2", Semver{3, 1, 2}},
		{"0.0.0", Semver{0, 0, 0}},
		{"10.20.30", Semver{10, 20, 30}},
	}
	for _, tt := range tests {
		got, ok := Parse(tt.input)
		if !ok {
			t.Errorf("Parse(%q) returned ok=false", tt.input)
			continue
		}
		if got != tt.want {
			t.Errorf("Parse(%q) = %+v, want %+v", tt.input, got, tt.want)
		}
	}
}

func TestParse_Invalid(t *testing.T) {
	tests := []string{
		"",
		"1",
		"1.2",
		"abc",
		"1.2.x",
		"a.b.c",
	}
	for _, input := range tests {
		if _, ok := Parse(input); ok {
			t.Errorf("Parse(%q) should return ok=false", input)
		}
	}
}

func TestParse_NegativeComponents(t *testing.T) {
	// Negative components are rejected because the pre-release/build-metadata
	// stripping step (IndexAny "-+") treats the leading minus as a suffix
	// delimiter and truncates the version string before it reaches Atoi.
	tests := []string{
		"-1.0.0", // '-' at index 0 truncates to ""
		"1.-2.3", // '-' at index 2 truncates to "1."
	}
	for _, input := range tests {
		if _, ok := Parse(input); ok {
			t.Errorf("Parse(%q) should return ok=false for negative components", input)
		}
	}
}

func TestParse_PreRelease(t *testing.T) {
	tests := []struct {
		input string
		want  Semver
	}{
		{"3.1.2-beta.1", Semver{3, 1, 2}},
		{"v1.0.0-rc1+build.123", Semver{1, 0, 0}},
		{"2.3.4+metadata", Semver{2, 3, 4}},
	}
	for _, tt := range tests {
		got, ok := Parse(tt.input)
		if !ok {
			t.Errorf("Parse(%q) returned ok=false", tt.input)
			continue
		}
		if got != tt.want {
			t.Errorf("Parse(%q) = %+v, want %+v", tt.input, got, tt.want)
		}
	}
}

func TestLessThan(t *testing.T) {
	tests := []struct {
		a, b Semver
		want bool
	}{
		// Major difference
		{Semver{1, 0, 0}, Semver{2, 0, 0}, true},
		{Semver{2, 0, 0}, Semver{1, 0, 0}, false},
		// Minor difference
		{Semver{1, 1, 0}, Semver{1, 2, 0}, true},
		{Semver{1, 2, 0}, Semver{1, 1, 0}, false},
		// Patch difference
		{Semver{1, 1, 1}, Semver{1, 1, 2}, true},
		{Semver{1, 1, 2}, Semver{1, 1, 1}, false},
		// Equal
		{Semver{1, 1, 1}, Semver{1, 1, 1}, false},
	}
	for _, tt := range tests {
		got := tt.a.LessThan(tt.b)
		if got != tt.want {
			t.Errorf("%+v.LessThan(%+v) = %v, want %v", tt.a, tt.b, got, tt.want)
		}
	}
}

func TestMinServer_NonZero(t *testing.T) {
	ms := MinServer()
	zero := Semver{}
	if ms == zero {
		t.Fatal("MinServer() should not be the zero value")
	}
}
