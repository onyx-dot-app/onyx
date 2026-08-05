package audit

import "testing"

// ecoVuln builds a GitHub Actions advisory with a single ECOSYSTEM range.
func ecoVuln(id string, events ...map[string]string) osvVuln {
	return osvVuln{
		ID: id,
		Affected: []osvAffected{{
			Package: osvPackage{Ecosystem: actionsEcosystem, Name: "tj-actions/changed-files"},
			Ranges:  []osvRange{{Type: "ECOSYSTEM", Events: events}},
		}},
	}
}

func TestAffectedByAdvisoryFixedRange(t *testing.T) {
	// introduced: 0, fixed: 46.0.1  (mirrors GHSA-mrrh-fwg8-r2c3)
	v := ecoVuln("GHSA-x", map[string]string{"introduced": "0"}, map[string]string{"fixed": "46.0.1"})
	cases := []struct {
		version string
		want    bool
	}{
		{"45.0.7", true},  // below fix
		{"46.0.0", true},  // still below fix
		{"46.0.1", false}, // exactly the fix -> patched
		{"46.0.2", false}, // above fix
		{"41", true},      // major-only tag below fix
	}
	for _, tc := range cases {
		if got := affectedByAdvisory(tc.version, v); got != tc.want {
			t.Errorf("affectedByAdvisory(%q) = %v, want %v", tc.version, got, tc.want)
		}
	}
}

func TestAffectedByAdvisoryLastAffected(t *testing.T) {
	v := ecoVuln("GHSA-y", map[string]string{"introduced": "0"}, map[string]string{"last_affected": "45.0.7"})
	if !affectedByAdvisory("45.0.7", v) {
		t.Error("45.0.7 should be affected (== last_affected)")
	}
	if affectedByAdvisory("45.0.8", v) {
		t.Error("45.0.8 should not be affected (> last_affected)")
	}
}

func TestAffectedByAdvisoryEnumeratedVersions(t *testing.T) {
	v := osvVuln{
		ID: "GHSA-z",
		Affected: []osvAffected{{
			Package:  osvPackage{Ecosystem: actionsEcosystem, Name: "a/b"},
			Versions: []string{"v44.0.0", "44.1.0"},
		}},
	}
	if !affectedByAdvisory("44.0.0", v) {
		t.Error("44.0.0 should match enumerated version (v-prefix normalized)")
	}
	if affectedByAdvisory("44.2.0", v) {
		t.Error("44.2.0 should not match")
	}
}

func TestAffectedByAdvisoryIgnoresOtherEcosystems(t *testing.T) {
	v := osvVuln{
		ID: "GHSA-npm",
		Affected: []osvAffected{{
			Package: osvPackage{Ecosystem: "npm", Name: "lodash"},
			Ranges:  []osvRange{{Type: "SEMVER", Events: []map[string]string{{"introduced": "0"}, {"fixed": "99.0.0"}}}},
		}},
	}
	if affectedByAdvisory("1.0.0", v) {
		t.Error("non-GitHub-Actions affected entries must be ignored")
	}
}

func TestFirstFixed(t *testing.T) {
	v := ecoVuln("GHSA-x", map[string]string{"introduced": "0"}, map[string]string{"fixed": "46.0.1"})
	if got := firstFixed(v); got != "46.0.1" {
		t.Errorf("firstFixed = %q, want 46.0.1", got)
	}
	// No fixed event -> empty.
	v2 := ecoVuln("GHSA-y", map[string]string{"introduced": "0"}, map[string]string{"last_affected": "45.0.7"})
	if got := firstFixed(v2); got != "" {
		t.Errorf("firstFixed = %q, want empty", got)
	}
}

func TestVersionForSHA(t *testing.T) {
	const sha = "de0fac2e4500dabe0009e67214ff5f5447ce83dd"
	tags := []ghTag{
		mkTag("v6", sha),
		mkTag("v6.0.2", sha),    // more specific tag on the same commit
		mkTag("v5.9.9", "othr"), // different commit
		mkTag("nightly", sha),   // non-semver, must be ignored
	}
	got, ok := versionForSHA(tags, sha)
	if !ok || got != "6.0.2" {
		t.Errorf("versionForSHA = (%q, %v), want (6.0.2, true)", got, ok)
	}

	if _, ok := versionForSHA(tags, "0000000000000000000000000000000000000000"); ok {
		t.Error("unknown sha should not resolve")
	}
}

func TestActionVersionTagPin(t *testing.T) {
	cache := map[string][]ghTag{}
	// A semver tag pin resolves directly without touching the cache/network.
	got, ok := actionVersion(actionRef{Name: "a/b", Ref: "v4.2.1", IsSHA: false}, cache)
	if !ok || got != "4.2.1" {
		t.Errorf("actionVersion(tag) = (%q, %v), want (4.2.1, true)", got, ok)
	}
	// A branch/floating ref is not comparable.
	if _, ok := actionVersion(actionRef{Name: "a/b", Ref: "main", IsSHA: false}, cache); ok {
		t.Error("branch ref should be unresolvable")
	}
}

func TestActionSeverity(t *testing.T) {
	v := osvVuln{DatabaseSpecific: map[string]any{"severity": "HIGH"}}
	if got := actionSeverity(v); got != SeverityHigh {
		t.Errorf("actionSeverity = %q, want high", got)
	}
	if got := actionSeverity(osvVuln{}); got != SeverityUnknown {
		t.Errorf("actionSeverity(empty) = %q, want unknown", got)
	}
}

func TestActionFindingConfirmed(t *testing.T) {
	ref := actionRef{Name: "tj-actions/changed-files", Ref: "45.0.7", Manifest: ".github/workflows/ci.yml"}
	v := ecoVuln("GHSA-mrrh-fwg8-r2c3", map[string]string{"introduced": "0"}, map[string]string{"fixed": "46.0.1"})
	v.Summary = "changed-files leaks secrets"
	v.DatabaseSpecific = map[string]any{"severity": "HIGH"}

	f := actionFinding(ref, v, true)
	if f.Source != SourceActions {
		t.Errorf("source = %q, want %q", f.Source, SourceActions)
	}
	if f.Severity != SeverityHigh {
		t.Errorf("severity = %q, want high", f.Severity)
	}
	if f.Package != "tj-actions/changed-files" || f.Version != "45.0.7" {
		t.Errorf("package/version wrong: %+v", f)
	}
	if f.Ecosystem != actionsEcosystem {
		t.Errorf("ecosystem = %q", f.Ecosystem)
	}
	if f.Title != "changed-files leaks secrets" {
		t.Errorf("title = %q", f.Title)
	}
	if f.FixedIn != "46.0.1" {
		t.Errorf("fixedIn = %q, want 46.0.1", f.FixedIn)
	}
	if f.URL != osvBaseURL+"GHSA-mrrh-fwg8-r2c3" {
		t.Errorf("url = %q", f.URL)
	}
	if f.Manifest != ".github/workflows/ci.yml" {
		t.Errorf("manifest = %q", f.Manifest)
	}
}

func TestActionFindingIndeterminate(t *testing.T) {
	ref := actionRef{Name: "tj-actions/changed-files", Ref: "0e58ed8671d6b60d0890c21b07f8835ace038e67"}
	v := ecoVuln("GHSA-mrrh-fwg8-r2c3")
	v.Summary = "changed-files leaks secrets"
	v.DatabaseSpecific = map[string]any{"severity": "HIGH"}

	f := actionFinding(ref, v, false)
	// Unresolved pins must not block the gate, so severity is demoted...
	if f.Severity != SeverityUnknown {
		t.Errorf("severity = %q, want unknown for unverified pin", f.Severity)
	}
	// ...and the title flags why.
	if f.Title != "unverified pin — changed-files leaks secrets" {
		t.Errorf("title = %q", f.Title)
	}
}

func TestDedupeRefs(t *testing.T) {
	refs := []actionRef{
		{Name: "a/b", Ref: "v1", Manifest: "w1.yml"},
		{Name: "a/b", Ref: "v1", Manifest: "w2.yml"}, // dup, dropped
		{Name: "a/b", Ref: "v2", Manifest: "w1.yml"},
		{Name: "c/d", Ref: "v1", Manifest: "w1.yml"},
	}
	got := dedupeRefs(refs)
	if len(got) != 3 {
		t.Fatalf("dedupeRefs len = %d, want 3", len(got))
	}
	if got[0].Manifest != "w1.yml" {
		t.Errorf("first manifest = %q, want w1.yml (first seen kept)", got[0].Manifest)
	}
}

func TestUniqueActionNames(t *testing.T) {
	refs := []actionRef{
		{Name: "a/b", Ref: "v1"},
		{Name: "a/b", Ref: "v2"},
		{Name: "c/d", Ref: "v1"},
	}
	got := uniqueActionNames(refs)
	if len(got) != 2 || got[0] != "a/b" || got[1] != "c/d" {
		t.Errorf("uniqueActionNames = %v, want [a/b c/d]", got)
	}
}

func TestCompositeSteps(t *testing.T) {
	composite := []byte(`
name: x
runs:
  using: composite
  steps:
    - uses: actions/checkout@v4
      shell: bash
    - run: echo hi
      shell: bash
`)
	steps, err := compositeSteps(composite)
	if err != nil || len(steps) != 2 {
		t.Fatalf("compositeSteps = (%d steps, %v), want (2, nil)", len(steps), err)
	}

	// Docker/JavaScript actions reference no other actions: a clean skip.
	docker := []byte("name: x\nruns:\n  using: docker\n  image: Dockerfile\n")
	if steps, err := compositeSteps(docker); err != nil || steps != nil {
		t.Errorf("docker action = (%v, %v), want (nil, nil)", steps, err)
	}

	// Malformed YAML must surface an error so the skipped file is visible.
	if _, err := compositeSteps([]byte("runs: [unclosed")); err == nil {
		t.Error("malformed yaml should return an error")
	}
}

func TestParseTagPages(t *testing.T) {
	// Modern gh --paginate merges pages into one array.
	single := []byte(`[{"name":"v1","commit":{"sha":"aaa"}},{"name":"v2","commit":{"sha":"bbb"}}]`)
	tags, err := parseTagPages(single)
	if err != nil || len(tags) != 2 {
		t.Fatalf("single: (%d tags, %v), want 2 tags", len(tags), err)
	}

	// Older gh --paginate concatenates one array per page without a wrapper.
	concat := []byte(`[{"name":"v1","commit":{"sha":"aaa"}}][{"name":"v2","commit":{"sha":"bbb"}}]`)
	tags, err = parseTagPages(concat)
	if err != nil || len(tags) != 2 {
		t.Fatalf("concatenated: (%d tags, %v), want 2 tags", len(tags), err)
	}
	if tags[1].Name != "v2" || tags[1].Commit.SHA != "bbb" {
		t.Errorf("second tag wrong: %+v", tags[1])
	}

	if tags, err := parseTagPages([]byte(`[]`)); err != nil || len(tags) != 0 {
		t.Errorf("empty page: (%d, %v), want 0 tags", len(tags), err)
	}
}

func TestInRangeToleratesDuplicateZeroEvents(t *testing.T) {
	// Malformed advisory with two introduced:0 events must not violate the sort's
	// ordering contract (panic) and should still evaluate correctly.
	events := []map[string]string{{"introduced": "0"}, {"introduced": "0"}, {"fixed": "2.0.0"}}
	if !inRange("1.0.0", events) {
		t.Error("1.0.0 should be affected (< fixed 2.0.0)")
	}
	if inRange("2.0.0", events) {
		t.Error("2.0.0 should be patched (== fixed)")
	}
}

func mkTag(name, sha string) ghTag {
	t := ghTag{Name: name}
	t.Commit.SHA = sha
	return t
}
