package terraform

import (
	"os"
	"path/filepath"
	"testing"
)

func ruleValues(findings []Finding) []string {
	out := make([]string, 0, len(findings))
	for _, f := range findings {
		out = append(out, f.Rule+" "+f.Value)
	}
	return out
}

func TestLintBytesRules(t *testing.T) {
	tests := []struct {
		name string
		src  string
		want []string
	}{
		{
			name: "clean file",
			src:  "variable \"cidr\" {\n  default = \"10.0.0.0/8\"\n}\n",
		},
		{
			name: "aws access key ids",
			src:  "a = \"AKIAIOSFODNN7EXAMPLE\"\nb = \"ASIA1234567890ABCDEF\"\n",
			want: []string{"access_key AKIAIOSFODNN7EXAMPLE", "access_key ASIA1234567890ABCDEF"},
		},
		{
			name: "short key is not an access key id",
			src:  "a = \"AKIAshort\"\n",
		},
		{
			name: "email address",
			src:  "owner = \"first.last+tag@sub.example.co.uk\"\n",
			want: []string{"email first.last+tag@sub.example.co.uk"},
		},
		{
			name: "routable cidr is flagged",
			src:  "c = \"8.8.8.8/32\"\n",
			want: []string{"cidr 8.8.8.8/32"},
		},
		{
			name: "private and reserved cidrs pass",
			src: "a = \"10.0.0.0/8\"\nb = \"172.16.0.0/12\"\nc = \"192.168.1.0/24\"\n" +
				"d = \"127.0.0.1/32\"\ne = \"169.254.0.0/16\"\nf = \"100.64.0.0/10\"\n" +
				"g = \"203.0.113.0/24\"\nh = \"0.0.0.0/0\"\n",
		},
		{
			name: "exactly twelve digits is an account id",
			src:  "a = \"123456789012\"\n",
			want: []string{"account_id 123456789012"},
		},
		{
			name: "longer and shorter digit runs are ignored",
			src:  "a = \"1234567890123\"\nb = \"12345678901\"\nc = \"0000000000000000\"\n",
		},
		{
			name: "unquoted account id is still flagged",
			src:  "a = 123456789012\n",
			want: []string{"account_id 123456789012"},
		},
		{
			name: "allow marker silences the line",
			src:  "a = \"123456789012\" # public-safe: ok\n",
		},
		{
			name: "allow marker must be exact",
			src:  "a = \"123456789012\" # public-safe: okay\n",
			want: []string{"account_id 123456789012"},
		},
		{
			name: "allow marker silences every hit on its line",
			src:  "a = \"ops@onyx.app 123456789012 8.8.8.8/32\" # public-safe: ok\n",
		},
		{
			name: "several hits on one line",
			src:  "a = \"ops@onyx.app 123456789012 8.8.8.8/32\"\n",
			want: []string{"email ops@onyx.app", "account_id 123456789012", "cidr 8.8.8.8/32"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := ruleValues(lintBytes([]byte(tt.src), "main.tf"))
			if len(got) != len(tt.want) {
				t.Fatalf("got %v, want %v", got, tt.want)
			}
			for i := range got {
				if got[i] != tt.want[i] {
					t.Errorf("finding %d: got %q, want %q", i, got[i], tt.want[i])
				}
			}
		})
	}
}

func TestLintBytesReportsLineNumbers(t *testing.T) {
	src := "one = 1\ntwo = 2\nthree = \"8.8.8.8/32\"\nfour = 4\nfive = \"ops@onyx.app\"\n"

	findings := lintBytes([]byte(src), "main.tf")
	if len(findings) != 2 {
		t.Fatalf("got %d findings, want 2", len(findings))
	}
	if findings[0].Line != 3 {
		t.Errorf("first finding on line %d, want 3", findings[0].Line)
	}
	if findings[1].Line != 5 {
		t.Errorf("second finding on line %d, want 5", findings[1].Line)
	}
}

func TestFindingString(t *testing.T) {
	f := Finding{Path: "modules/aws/vpc/main.tf", Line: 12, Rule: RuleCIDR, Value: "8.8.8.8/32"}
	want := "modules/aws/vpc/main.tf:12: routable IPv4 CIDR 8.8.8.8/32"
	if got := f.String(); got != want {
		t.Errorf("got %q, want %q", got, want)
	}
}

func TestLintFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "main.tf")
	if err := os.WriteFile(path, []byte("c = \"8.8.8.8/32\"\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	findings, err := LintFile(path, "main.tf")
	if err != nil {
		t.Fatal(err)
	}
	if len(findings) != 1 || findings[0].Rule != RuleCIDR {
		t.Fatalf("got %v, want one cidr finding", findings)
	}
}
