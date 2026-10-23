package sanitize

import "testing"

func TestTerminal(t *testing.T) {
	cases := map[string]struct{ in, want string }{
		"osc52 clipboard":   {"a\x1b]52;c;ZWNobyBoaQ==\x07b", "ab"},
		"osc8 hyperlink":    {"\x1b]8;;https://evil\x1b\\click\x1b]8;;\x1b\\", "click"},
		"csi erase":         {"x\x1b[2Jy", "xy"},
		"lone bel":          {"ding\x07", "ding"},
		"split sequence":    {"]52;c;ZWNobw==\x07", "]52;c;ZWNobw=="},
		"carriage return":   {"safe\rrm -rf", "saferm -rf"},
		"c1 csi":            {"a\u009b2Jb", "a2Jb"},
		"raw c1 byte":       {"a\x9b2Jb\xff", "ab"},
		"del":               {"a\x7fb", "ab"},
		"keeps newline tab": {"line 1\n\tline 2 — ok ✓", "line 1\n\tline 2 — ok ✓"},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			if got := Terminal(tc.in); got != tc.want {
				t.Errorf("Terminal(%q) = %q, want %q", tc.in, got, tc.want)
			}
		})
	}
}

func TestLine(t *testing.T) {
	if got := Line("Help\x1b[2J\nDesk\tx\r\x07"); got != "Help Desk x" {
		t.Errorf("Line = %q, want %q", got, "Help Desk x")
	}
}
