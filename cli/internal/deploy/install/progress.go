package install

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/onyx-dot-app/onyx/cli/internal/deploy/dockercmd"
	"github.com/onyx-dot-app/onyx/cli/internal/deploy/ui"
	"github.com/onyx-dot-app/onyx/cli/internal/version"
)

// Compose progress formats, richest first: json carries per-layer byte
// counters, plain only the event stream. Both are read here; compose's default
// tty renderer is deliberately never used while the wizard is up, because it
// redraws with cursor moves on a screen the wizard has had to release, leaving
// the phase invisible until the command finishes.
const (
	progressJSON  = "json"
	progressPlain = "plain"

	// The global --progress flag landed in compose 2.19, its json mode in
	// 2.29; older versions reject the value outright.
	minProgressVersion     = "2.19.0"
	minProgressJSONVersion = "2.29.0"

	// `pull --policy` landed in compose 2.22.
	minPullPolicyVersion = "2.22.0"
)

const (
	// progressRefresh throttles wizard updates: compose reports a layer event
	// per downloaded chunk, far more often than a terminal can usefully
	// repaint.
	progressRefresh = 150 * time.Millisecond
	// maxProgressRows caps a checklist. The deployment has a handful of
	// images and containers, so more rows than this means the output wasn't
	// what we parsed it as, and the wizard pane must not grow past the screen.
	maxProgressRows = 24
)

// progressMode picks the richest progress format this compose understands, or
// "" when the wizard isn't driving the run (plain output already streams) or
// compose predates the flag.
func (in *installer) progressMode(ctx context.Context) string {
	if in.wiz == nil || in.opts.Verbose || in.compose == nil {
		return ""
	}
	switch {
	case in.composeAtLeast(ctx, minProgressJSONVersion):
		return progressJSON
	case in.composeAtLeast(ctx, minProgressVersion):
		return progressPlain
	default:
		return ""
	}
}

// composeAtLeast reports whether the installed compose is at least min. A
// version that doesn't parse ("dev" builds) counts as too old: an unknown flag
// fails the command outright, which is not a trade worth making for output.
func (in *installer) composeAtLeast(ctx context.Context, min string) bool {
	if in.compose == nil {
		return false
	}
	have, ok := version.Parse(in.compose.Version(ctx))
	if !ok {
		return false
	}
	want, _ := version.Parse(min)
	return !have.LessThan(want)
}

// composeEvent is compose's json progress event, narrowed to the fields these
// phases read. Text is the event's own word ("Pulling", "Downloading"), Status
// its detail — except for container lifecycle events, which carry the word in
// Status and leave Text empty.
type composeEvent struct {
	ID       string `json:"id"`
	ParentID string `json:"parent_id"`
	Text     string `json:"text"`
	Status   string `json:"status"`
	Current  int64  `json:"current"`
	Total    int64  `json:"total"`
	Percent  int    `json:"percent"`
}

// checklist is the shared state behind the live per-row panes: insertion
// ordered rows, capped, pushed to the wizard at a bounded rate.
type checklist struct {
	services func([]ui.ServiceRow)
	extra    func(string)

	order []string
	last  time.Time
}

// track reports whether name is a new row, refusing rows past the cap.
func (c *checklist) track(name string) (known, created bool) {
	for _, n := range c.order {
		if n == name {
			return true, false
		}
	}
	if len(c.order) >= maxProgressRows {
		return false, false
	}
	c.order = append(c.order, name)
	return true, true
}

// due reports whether an update should be pushed now. Structural changes (a
// new row, or one reaching its final state) always are; the churn in between
// is rate-limited.
func (c *checklist) due(structural bool) bool {
	if !structural && time.Since(c.last) < progressRefresh {
		return false
	}
	c.last = time.Now()
	return true
}

// pullProgress turns `docker compose pull` progress output into a live
// per-image checklist with download totals.
//
// json events name the image in "id" for image-level phases ("Pulling",
// "Pulled", "Skipped - …") and in "parent_id" for the layer events carrying
// the byte counters summed here. plain prints "<id> <text> <status text>"
// instead, which still identifies images but has no usable counters, so those
// runs get the checklist alone.
//
// Anything unrecognized is ignored: the phase then shows its spinner and
// elapsed time, exactly as it would with no progress output at all.
type pullProgress struct {
	checklist
	images map[string]*pullImage
}

type pullImage struct {
	done bool
	// phase is what the image's layers are busy with, shown when there are no
	// bytes to show — an image whose layers are all present locally moves
	// through this checklist without a single counter.
	phase string
	rank  int
	// note is how the image finished, when that is worth more than the tick:
	// why it was skipped, or that it failed.
	note   string
	layers map[string]*pullLayer
}

// pullLayer is one layer's download, in bytes.
type pullLayer struct{ current, total int64 }

func newPullProgress(services func([]ui.ServiceRow), extra func(string)) *pullProgress {
	return &pullProgress{
		checklist: checklist{services: services, extra: extra},
		images:    map[string]*pullImage{},
	}
}

// line consumes one output line. It is called from the single goroutine
// draining the command's output, so the state needs no lock.
func (p *pullProgress) line(s string) {
	if e, ok := decodeEvent(s); ok {
		if known, structural := p.event(e); known && p.due(structural) {
			p.publish()
		}
	}
}

func (p *pullProgress) event(e composeEvent) (known, structural bool) {
	if e.ParentID == "" {
		return p.imageEvent(e.ID, e.Text)
	}
	phase, ok := pullPhases[e.Text]
	if !ok {
		return false, false
	}
	img, _ := p.image(e.ParentID)
	if img == nil {
		return false, false
	}
	layer := img.layers[e.ID]
	if layer == nil {
		layer = &pullLayer{}
		img.layers[e.ID] = layer
	}
	// Only the download itself is counted: "Extracting" reports the same
	// layer's uncompressed size, which would make the total jump around.
	switch e.Text {
	case "Downloading":
		layer.current, layer.total = e.Current, e.Total
	case "Download complete", "Pull complete", "Already exists":
		// Finished layers report no counters at all, so hold them at the
		// last total they announced rather than letting the sum shrink.
		layer.current = layer.total
	}
	// Layers finish out of order, so the image shows the furthest phase any of
	// them has reached rather than whichever reported last.
	if phase.rank > img.rank {
		img.rank, img.phase = phase.rank, phase.word
	}
	return true, false
}

// pullPhases ranks the per-layer phases docker reports, with what the checklist
// says while an image sits in each.
var pullPhases = map[string]struct {
	rank int
	word string
}{
	"Preparing":          {1, "preparing"},
	"Pulling fs layer":   {1, "preparing"},
	"Waiting":            {1, "preparing"},
	"Already exists":     {2, "already present"},
	"Downloading":        {3, "downloading"},
	"Verifying Checksum": {4, "verifying"},
	"Download complete":  {4, "downloaded"},
	"Extracting":         {5, "extracting"},
	"Pull complete":      {6, "unpacked"},
}

// imageEvent records an image-level phase. Everything but "Pulling" ends the
// image: compose reports skipped and failed images once and never mentions
// them again.
func (p *pullProgress) imageEvent(name, text string) (known, structural bool) {
	word := firstWord(text)
	switch word {
	case "Pulling", "Pulled", "Skipped", "Warning", "Error":
	default:
		return false, false
	}
	img, created := p.image(name)
	if img == nil {
		return false, false
	}
	switch word {
	case "Skipped":
		// Compose skips an image for several reasons ("Skipped - Image is
		// already present locally", "- No image to be pulled"); the one an
		// operator is owed an explanation for is the cached image.
		img.note = "skipped"
		if strings.Contains(text, "already present") {
			img.note = "already present"
		}
	case "Error":
		img.note = "failed"
	case "Warning":
		img.note = "warning"
	}
	done := word != "Pulling"
	structural = created || img.done != done
	img.done = done
	return true, structural
}

// image returns the image's state, adding it to the checklist on first sight
// (layer events can arrive before the image's own "Pulling"). A nil result
// means the row cap was reached.
func (p *pullProgress) image(name string) (img *pullImage, created bool) {
	known, created := p.track(name)
	if !known {
		return nil, false
	}
	img = p.images[name]
	if img == nil {
		img = &pullImage{layers: map[string]*pullLayer{}}
		p.images[name] = img
	}
	return img, created
}

// publish repaints the checklist: one row per image, with how much of it has
// come down, plus the overall total on the task line.
func (p *pullProgress) publish() {
	rows := make([]ui.ServiceRow, 0, len(p.order))
	done := 0
	var current, total int64
	for _, name := range p.order {
		img := p.images[name]
		cur, tot := img.bytes()
		current, total = current+cur, total+tot
		row := ui.ServiceRow{Name: name, Ready: img.done}
		switch {
		case img.done:
			done++
			row.Detail = img.finished(tot)
		case cur < tot:
			row.Detail = fmt.Sprintf("%d%%  %s / %s", cur*100/tot, humanBytes(cur), humanBytes(tot))
		default:
			// Nothing is moving over the network: either the layers are all
			// local, or the download is done and the image is being unpacked.
			row.Detail = img.phase
		}
		rows = append(rows, row)
	}
	p.services(rows)

	extra := fmt.Sprintf("%d/%d images", done, len(rows))
	if total > 0 {
		extra += fmt.Sprintf(" · %s / %s", humanBytes(current), humanBytes(total))
	}
	p.extra(extra)
}

// finished is what a completed image's row says: why it was skipped, how much
// came down, or that there was nothing to fetch.
func (img *pullImage) finished(total int64) string {
	switch {
	case img.note != "":
		return img.note
	case total > 0:
		return humanBytes(total)
	default:
		return "up to date"
	}
}

// bytes sums the image's layers. Layers already present locally announce no
// size and simply count as nothing.
func (img *pullImage) bytes() (current, total int64) {
	for _, l := range img.layers {
		current, total = current+l.current, total+l.total
	}
	return current, total
}

// startProgress turns `docker compose up` progress output into a live
// per-container checklist. Compose names every transition it makes, which is
// the only way to tell a container that is being replaced from one that is
// coming up: `docker ps` shows the outgoing container as healthy right up to
// the moment it is stopped, so a --force-recreate rollout otherwise looks like
// a stack that is already fully up.
//
// Container events carry "Container <name>" as the id and the phase word in
// "status" ("Recreate", "Starting", "Waiting", "Healthy"). Everything else
// compose touches (networks, volumes) is ignored.
type startProgress struct {
	checklist
	// waitHealth records that `up --wait` is in play, so a started container
	// is only halfway there: compose follows it with a health check.
	waitHealth bool
	states     map[string]string
}

func newStartProgress(services func([]ui.ServiceRow), extra func(string), waitHealth bool) *startProgress {
	return &startProgress{
		checklist:  checklist{services: services, extra: extra},
		waitHealth: waitHealth,
		states:     map[string]string{},
	}
}

func (p *startProgress) line(s string) {
	e, ok := decodeEvent(s)
	if !ok {
		return
	}
	name, isContainer := strings.CutPrefix(e.ID, "Container ")
	if !isContainer {
		return
	}
	// "Skipped: <reason>" is the one phase word carrying its own punctuation.
	word := strings.TrimSuffix(firstWord(e.Status), ":")
	if _, ok := startPhases[word]; !ok {
		return
	}
	name = shortContainerName(name)
	known, created := p.track(name)
	if !known {
		return
	}
	structural := created || p.ready(p.states[name]) != p.ready(word)
	p.states[name] = word
	if p.due(structural) {
		p.publish()
	}
}

func (p *startProgress) publish() {
	rows := make([]ui.ServiceRow, 0, len(p.order))
	done := 0
	for _, name := range p.order {
		ready := p.ready(p.states[name])
		if ready {
			done++
		}
		rows = append(rows, ui.ServiceRow{Name: name, Detail: startPhases[p.states[name]], Ready: ready})
	}
	p.services(rows)
	p.extra(fmt.Sprintf("%d/%d ready", done, len(rows)))
}

// ready reports whether a container has reached its final state for this run.
func (p *startProgress) ready(word string) bool {
	switch word {
	case "Healthy", "Exited", "Skipped":
		return true
	case "Started", "Running", "Restarted":
		// Without --wait these are as far as the run goes; with it, compose
		// keeps polling health and reports again.
		return !p.waitHealth
	}
	return false
}

// startPhases maps compose's container status words to what the checklist
// shows next to the container. Words outside this set are compose internals
// the operator has no use for.
var startPhases = map[string]string{
	"Creating":   "creating",
	"Created":    "created",
	"Recreate":   "replacing",
	"Recreated":  "replaced",
	"Restart":    "restarting",
	"Restarted":  "restarted",
	"Stopping":   "stopping",
	"Stopped":    "stopped",
	"Killing":    "stopping",
	"Killed":     "stopped",
	"Removing":   "removing",
	"Removed":    "removed",
	"Starting":   "starting",
	"Started":    "started",
	"Running":    "running",
	"Waiting":    "waiting for health",
	"Healthy":    "healthy",
	"Exited":     "exited",
	"Skipped":    "skipped",
	"Error":      "failed",
	"Restarting": "restarting",
}

// decodeEvent reads one progress line in either format. plain prints the
// fields space-separated (" <id> <text> <status text>"), which stays
// unambiguous only because compose's ids are either a single word or the
// "<Kind> <name>" pair this rejoins.
func decodeEvent(s string) (composeEvent, bool) {
	s = strings.TrimSpace(s)
	if s == "" {
		return composeEvent{}, false
	}
	if strings.HasPrefix(s, "{") {
		var e composeEvent
		if err := json.Unmarshal([]byte(s), &e); err != nil || e.ID == "" {
			return composeEvent{}, false
		}
		return e, true
	}
	fields := strings.Fields(s)
	if len(fields) < 2 {
		return composeEvent{}, false
	}
	if _, ok := composeObjects[fields[0]]; ok {
		if len(fields) < 3 {
			return composeEvent{}, false
		}
		return composeEvent{ID: fields[0] + " " + fields[1], Status: strings.Join(fields[2:], " ")}, true
	}
	if isLayerID(fields[0]) {
		// A layer's plain line has no parseable counters ("12.3MB/45MB" as
		// free text), and dropping it keeps layers out of the image list.
		return composeEvent{}, false
	}
	return composeEvent{ID: fields[0], Text: strings.Join(fields[1:], " ")}, true
}

// composeObjects are the id prefixes compose gives non-image events; they are
// what makes an id two words long.
var composeObjects = map[string]struct{}{
	"Container": {}, "Network": {}, "Volume": {}, "Image": {},
}

// shortContainerName trims the parts of a compose container name every row
// would repeat: the project prefix and the replica index.
func shortContainerName(name string) string {
	name = strings.TrimPrefix(name, dockercmd.ProjectName+"-")
	if i := strings.LastIndexByte(name, '-'); i > 0 && isDigits(name[i+1:]) {
		name = name[:i]
	}
	return name
}

func isDigits(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

func firstWord(s string) string {
	if i := strings.IndexByte(s, ' '); i >= 0 {
		return s[:i]
	}
	return s
}

// isLayerID reports whether s looks like docker's truncated layer id rather
// than a compose service name.
func isLayerID(s string) bool {
	if len(s) < 8 {
		return false
	}
	for _, r := range s {
		if !strings.ContainsRune("0123456789abcdef", r) {
			return false
		}
	}
	return true
}

// humanBytes renders download sizes the way docker does: decimal units, with
// enough precision to see the number move.
func humanBytes(n int64) string {
	const k = 1000
	switch {
	case n < k*k:
		return fmt.Sprintf("%.0f kB", float64(n)/k)
	case n < k*k*k:
		return fmt.Sprintf("%.1f MB", float64(n)/(k*k))
	default:
		return fmt.Sprintf("%.2f GB", float64(n)/(k*k*k))
	}
}

// lineWriter feeds whole lines to emit as they arrive, so a long-running
// command can drive the UI while it is still writing.
type lineWriter struct {
	buf  bytes.Buffer
	emit func(string)
}

func (w *lineWriter) Write(p []byte) (int, error) {
	w.buf.Write(p)
	for {
		line, err := w.buf.ReadString('\n')
		if err != nil {
			// Partial line: put it back and wait for the rest.
			w.buf.WriteString(line)
			return len(p), nil
		}
		w.emit(strings.TrimRight(line, "\r\n"))
	}
}
