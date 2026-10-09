package install

import (
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/ui"
)

// checklistSink collects what a tracker would push to the wizard.
type checklistSink struct {
	rows  []ui.ServiceRow
	extra string
}

func (s *checklistSink) hooks() (func([]ui.ServiceRow), func(string)) {
	return func(r []ui.ServiceRow) { s.rows = r }, func(e string) { s.extra = e }
}

// render flattens the checklist the way the pane shows it, so assertions read
// like the screen: "name state" per row, ✓ for finished.
func (s *checklistSink) render() string {
	out := make([]string, 0, len(s.rows))
	for _, r := range s.rows {
		mark := " "
		if r.Ready {
			mark = "✓"
		}
		row := mark + r.Name
		if r.Detail != "" {
			row += " " + r.Detail
		}
		out = append(out, row)
	}
	return strings.Join(out, ",")
}

// Plain progress carries no counters, so the pull checklist is just which
// images are done. Layer events (hex ids) are noise at this level.
func TestPullProgressPlainTracksImages(t *testing.T) {
	var sink checklistSink
	p := newPullProgress(sink.hooks())
	w := &lineWriter{emit: p.line}
	if _, err := w.Write([]byte(" backend Pulling \n relational_db Pulling \n 9d8e18e5f8e4 Pulling fs layer \n" +
		" 9d8e18e5f8e4 Downloading [====>   ]  5.5MB/50MB\n 9d8e18e5f8e4 Waiting \n cache Skipped ")); err != nil {
		t.Fatal(err)
	}
	if _, err := w.Write([]byte("- Image is already present locally\n backend Pulled \n")); err != nil {
		t.Fatal(err)
	}

	// An image that was already on the host reads as pulled: the row answers
	// "is this image here", not "did bytes move".
	if got := sink.render(); got != "✓backend pulled, relational_db,✓cache pulled" {
		t.Errorf("rows = %q", got)
	}
	if sink.extra != "2/3 images" {
		t.Errorf("extra = %q", sink.extra)
	}
}

// An image whose layers are all on the host reports no byte counters at all,
// so its row has to say what is happening some other way.
func TestPullProgressReportsCachedLayers(t *testing.T) {
	var sink checklistSink
	p := newPullProgress(sink.hooks())
	for _, line := range []string{
		`{"id":"cache","text":"Pulling"}`,
		`{"id":"9d8e18e5f8e4","parent_id":"cache","text":"Already exists"}`,
		`{"id":"5f8e4a1b2c3d","parent_id":"cache","text":"Already exists"}`,
	} {
		p.line(line)
	}
	p.publish()

	if got := sink.render(); got != " cache already present" {
		t.Errorf("rows = %q", got)
	}

	// Downloaded layers still have to be unpacked, which is the other phase
	// with no bytes left to count.
	p.line(`{"id":"5f8e4a1b2c3d","parent_id":"cache","text":"Extracting","current":2,"total":4}`)
	p.publish()
	if got := sink.render(); got != " cache extracting" {
		t.Errorf("rows = %q", got)
	}
}

// json progress adds per-layer byte counters, which the checklist sums into
// per-image download progress.
func TestPullProgressReportsDownloadedBytes(t *testing.T) {
	var sink checklistSink
	p := newPullProgress(sink.hooks())
	for _, line := range []string{
		`{"id":"backend","text":"Pulling"}`,
		`{"id":"5f8e4a1b2c3d","parent_id":"backend","text":"Downloading","current":524288,"total":2097152,"percent":25}`,
		`{"id":"9d8e18e5f8e4","parent_id":"backend","text":"Downloading","current":1048576,"total":1048576,"percent":100}`,
		// Completed layers report no counters at all: the total must not drop.
		`{"id":"9d8e18e5f8e4","parent_id":"backend","text":"Download complete","percent":100}`,
		// Extraction reports the uncompressed size — not a download.
		`{"id":"9d8e18e5f8e4","parent_id":"backend","text":"Extracting","current":4194304,"total":8388608}`,
		`{"id":"relational_db","text":"Pulling"}`,
	} {
		p.line(line)
	}
	p.publish() // byte updates are rate-limited; render what has accumulated

	if got := sink.render(); got != " backend 50%  1.6 MB / 3.1 MB, relational_db" {
		t.Errorf("rows = %q", got)
	}
	if sink.extra != "0/2 images · 1.6 MB / 3.1 MB" {
		t.Errorf("extra = %q", sink.extra)
	}
}

// The wizard asks compose for json, so a failed phase's captured output has to
// be turned back into something readable before it is shown as scrollback.
func TestFailureTailRendersEvents(t *testing.T) {
	captured := strings.Join([]string{
		`{"id":"Container onyx-api_server-1","status":"Starting"}`,
		`{"id":"9d8e18e5f8e4","parent_id":"backend","text":"Downloading","current":5,"total":50}`,
		`{"dry-run":false}`,
		`{"tail":true,"text":"container onyx-api_server-1 is unhealthy"}`,
		`Error response from daemon: no such image`,
		``,
	}, "\n")

	got := failureTail(captured, 10)
	want := []string{
		"Container onyx-api_server-1 Starting",
		"9d8e18e5f8e4 Downloading",
		"container onyx-api_server-1 is unhealthy",
		"Error response from daemon: no such image",
	}
	if strings.Join(got, "|") != strings.Join(want, "|") {
		t.Errorf("tail = %q, want %q", got, want)
	}

	// The tail is the end of the output, so the error that ended the run is
	// what survives the cut.
	if got := failureTail(captured, 1); len(got) != 1 || got[0] != want[len(want)-1] {
		t.Errorf("capped tail = %q", got)
	}
}

// The start checklist has to say which container is being replaced and which
// is coming up: with --force-recreate both happen, and `docker ps` alone can't
// tell them apart.
func TestStartProgressSeparatesStoppingFromStarting(t *testing.T) {
	var sink checklistSink
	services, extra := sink.hooks()
	p := newStartProgress(services, extra, true, "onyx")

	for _, line := range []string{
		`{"id":"Network onyx_default","status":"Created"}`,
		`{"id":"Container onyx-relational_db-1","status":"Running"}`,
		`{"id":"Container onyx-api_server-1","status":"Recreate"}`,
		`{"id":"Container onyx-api_server-1","status":"Recreated"}`,
		`{"id":"Container onyx-api_server-1","status":"Starting"}`,
		`{"id":"Container onyx-api_server-1","status":"Started"}`,
		`{"id":"Container onyx-relational_db-1","status":"Waiting"}`,
		`{"id":"Container onyx-relational_db-1","status":"Healthy"}`,
	} {
		p.line(line)
	}
	p.publish()

	// --wait is in play, so a started container is not done until healthy.
	if got := sink.render(); got != "✓relational_db healthy, api_server started" {
		t.Errorf("rows = %q", got)
	}
	if sink.extra != "1/2 ready" {
		t.Errorf("extra = %q", sink.extra)
	}
}

// The health poll runs behind the event stream, so it has to know when the
// stream has taken over — and say the same things while it hasn't.
func TestStartProgressBacksOffOnceComposeSpeaks(t *testing.T) {
	var sink checklistSink
	services, extra := sink.hooks()
	p := newStartProgress(services, extra, true, "onyx")

	// Networks and volumes are not the rollout: until a container is named,
	// the checklist is still empty and the poll is what fills it.
	p.line(`{"id":"Network onyx_default","status":"Created"}`)
	if p.reporting() {
		t.Error("a network event is not a per-service report")
	}
	p.line(`{"id":"Container onyx-api_server-1","status":"Starting"}`)
	if !p.reporting() {
		t.Error("a container event should hand the checklist to the event stream")
	}

	// Whichever side fills the checklist, a row reads the same.
	for _, tc := range []struct{ status, want string }{
		{"Up 2 minutes (healthy)", "healthy"},
		{"Up 3 seconds (health: starting)", "waiting"},
		{"Up 9 minutes (unhealthy)", "unhealthy"},
		{"Up About an hour", "running"},
		{"Restarting (1) 4 seconds ago", "restarting"},
		{"Exited (0) 1 minute ago", "exited"},
	} {
		if got := healthDetail(tc.status); got != tc.want {
			t.Errorf("healthDetail(%q) = %q, want %q", tc.status, got, tc.want)
		}
	}
}

// A container list shows what is running, not what a rollout is doing. Against
// the containers the phase started with, it shows all three states: waiting its
// turn, mid-swap, and up on the new deployment.
func TestWatchRowsTellsReplacedFromPending(t *testing.T) {
	w := healthWatch{
		before: map[string]string{
			"api_server":      "aaaa1111",
			"background":      "bbbb2222",
			"relational_db":   "cccc3333",
			"inference_model": "dddd4444",
		},
		recreate: true,
		project:  "onyx",
	}
	// background's container is gone from the list: it is between the two.
	ps := strings.Join([]string{
		"onyx-relational_db-1\tcccc3333\tUp 2 hours (healthy)",
		"onyx-api_server-1\t9999eeee\tUp 4 seconds (health: starting)",
		"onyx-inference_model-1\t8888ffff\tUp 30 seconds (healthy)",
	}, "\n")

	rows, ready := watchRows(ps, w)
	var sink checklistSink
	sink.rows = rows
	want := " api_server waiting, background restarting,✓inference_model healthy, relational_db pending"
	if got := sink.render(); got != want {
		t.Errorf("rows = %q, want %q", got, want)
	}
	if ready != 1 {
		t.Errorf("ready = %d, want 1", ready)
	}

	// Without a recreate, compose is free to leave a container alone, so the
	// one it kept is done rather than pending.
	w.recreate = false
	if _, ready := watchRows(ps, w); ready != 2 {
		t.Errorf("ready = %d, want 2", ready)
	}
}

// Plain progress names containers the same way, just space-separated.
func TestStartProgressPlainLines(t *testing.T) {
	var sink checklistSink
	services, extra := sink.hooks()
	p := newStartProgress(services, extra, false, "onyx")
	w := &lineWriter{emit: p.line}
	if _, err := w.Write([]byte(" Volume \"onyx_db_volume\"  Created\n Container onyx-cache-1  Recreate\n" +
		" Container onyx-cache-1  Recreated\n Container onyx-cache-1  Started\n")); err != nil {
		t.Fatal(err)
	}

	// No --wait: started is as far as this run goes.
	if got := sink.render(); got != "✓cache started" {
		t.Errorf("rows = %q", got)
	}
	if sink.extra != "1/1 ready" {
		t.Errorf("extra = %q", sink.extra)
	}
}
