package imgdiff

import (
	"bytes"
	"encoding/base64"
	"fmt"
	"html/template"
	"image"
	"image/png"
	"os"
	"path/filepath"
)

// reportEntry holds data for a single screenshot in the HTML template.
type reportEntry struct {
	Name            string
	Status          string
	DiffPercent     string
	BaselineDataURI template.URL
	CurrentDataURI  template.URL
	DiffDataURI     template.URL
	HasBaseline     bool
	HasCurrent      bool
	HasDiff         bool
}

// reportData holds all data for the HTML template.
type reportData struct {
	Entries        []reportEntry
	ChangedCount   int
	AddedCount     int
	RemovedCount   int
	UnchangedCount int
	TotalCount     int
	HasDifferences bool
}

// GenerateReport produces a self-contained HTML file from comparison results.
// All images are base64-encoded inline as data URIs.
func GenerateReport(results []Result, outputPath string) error {
	if err := os.MkdirAll(filepath.Dir(outputPath), 0755); err != nil {
		return fmt.Errorf("failed to create output directory: %w", err)
	}

	data := reportData{}

	for _, r := range results {
		entry := reportEntry{
			Name:   r.Name,
			Status: r.Status.String(),
		}

		switch r.Status {
		case StatusChanged:
			data.ChangedCount++
			entry.DiffPercent = fmt.Sprintf("%.2f%%", r.DiffPercent)
		case StatusAdded:
			data.AddedCount++
		case StatusRemoved:
			data.RemovedCount++
		case StatusUnchanged:
			data.UnchangedCount++
			entry.DiffPercent = "0.00%"
		}

		if r.BaselinePath != "" {
			uri, err := pngFileToDataURI(r.BaselinePath)
			if err != nil {
				return fmt.Errorf("failed to encode baseline %s: %w", r.Name, err)
			}
			entry.BaselineDataURI = template.URL(uri)
			entry.HasBaseline = true
		}

		if r.CurrentPath != "" {
			uri, err := pngFileToDataURI(r.CurrentPath)
			if err != nil {
				return fmt.Errorf("failed to encode current %s: %w", r.Name, err)
			}
			entry.CurrentDataURI = template.URL(uri)
			entry.HasCurrent = true
		}

		if r.DiffImage != nil {
			uri, err := imageToDataURI(r.DiffImage)
			if err != nil {
				return fmt.Errorf("failed to encode diff %s: %w", r.Name, err)
			}
			entry.DiffDataURI = template.URL(uri)
			entry.HasDiff = true
		}

		data.Entries = append(data.Entries, entry)
	}

	data.TotalCount = len(results)
	data.HasDifferences = data.ChangedCount > 0 || data.AddedCount > 0 || data.RemovedCount > 0

	tmpl, err := template.New("report").Parse(htmlTemplate)
	if err != nil {
		return fmt.Errorf("failed to parse template: %w", err)
	}

	f, err := os.Create(outputPath)
	if err != nil {
		return fmt.Errorf("failed to create output file: %w", err)
	}
	defer func() { _ = f.Close() }()

	if err := tmpl.Execute(f, data); err != nil {
		return fmt.Errorf("failed to execute template: %w", err)
	}

	return nil
}

// pngFileToDataURI reads a PNG file and returns a base64 data URI.
func pngFileToDataURI(path string) (string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	encoded := base64.StdEncoding.EncodeToString(data)
	return "data:image/png;base64," + encoded, nil
}

// imageToDataURI encodes an image.Image to a PNG base64 data URI.
func imageToDataURI(img image.Image) (string, error) {
	var buf bytes.Buffer
	if err := png.Encode(&buf, img); err != nil {
		return "", err
	}
	encoded := base64.StdEncoding.EncodeToString(buf.Bytes())
	return "data:image/png;base64," + encoded, nil
}

const htmlTemplate = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Visual Regression Report</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; color: #333; }
  .header { background: #1a1a2e; color: #fff; padding: 24px 32px; }
  .header h1 { font-size: 24px; font-weight: 600; }
  .header p { margin-top: 8px; opacity: 0.8; font-size: 14px; }
  .summary { display: flex; gap: 16px; padding: 20px 32px; background: #fff; border-bottom: 1px solid #e0e0e0; flex-wrap: wrap; }
  .summary-card { padding: 12px 20px; border-radius: 8px; font-size: 14px; font-weight: 500; }
  .summary-changed { background: #fff3e0; color: #e65100; }
  .summary-added { background: #e8f5e9; color: #2e7d32; }
  .summary-removed { background: #fce4ec; color: #c62828; }
  .summary-unchanged { background: #e3f2fd; color: #1565c0; }
  .content { padding: 24px 32px; max-width: 1400px; margin: 0 auto; }
  .section-title { font-size: 18px; font-weight: 600; margin: 24px 0 16px; padding-bottom: 8px; border-bottom: 2px solid #e0e0e0; }
  .no-changes { text-align: center; padding: 60px 20px; color: #666; }
  .no-changes h2 { font-size: 24px; margin-bottom: 8px; color: #2e7d32; }
  .card { background: #fff; border-radius: 12px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden; }
  .card-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid #eee; }
  .card-name { font-weight: 600; font-size: 15px; }
  .card-badge { font-size: 12px; padding: 4px 10px; border-radius: 12px; font-weight: 500; }
  .badge-changed { background: #fff3e0; color: #e65100; }
  .badge-added { background: #e8f5e9; color: #2e7d32; }
  .badge-removed { background: #fce4ec; color: #c62828; }
  .tabs { display: flex; gap: 0; border-bottom: 1px solid #eee; }
  .tab { padding: 10px 20px; cursor: pointer; font-size: 13px; font-weight: 500; color: #666; border-bottom: 2px solid transparent; transition: all 0.2s; }
  .tab:hover { color: #333; background: #f9f9f9; }
  .tab.active { color: #1a1a2e; border-bottom-color: #1a1a2e; }
  .tab-content { display: none; padding: 20px; }
  .tab-content.active { display: block; }
  .slider-container { position: relative; overflow: hidden; cursor: ew-resize; user-select: none; border: 1px solid #eee; border-radius: 4px; }
  .slider-container > img { display: block; width: 100%; height: auto; }
  .slider-baseline { position: absolute; top: 0; left: 0; width: 100%; height: 100%; clip-path: inset(0 50% 0 0); }
  .slider-baseline img { display: block; width: 100%; height: auto; }
  .slider-divider { position: absolute; top: 0; width: 3px; height: 100%; background: #e65100; z-index: 10; cursor: ew-resize; }
  .slider-divider::before { content: ""; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 32px; height: 32px; background: #e65100; border-radius: 50%; border: 2px solid #fff; box-shadow: 0 2px 8px rgba(0,0,0,0.3); }
  .slider-divider::after { content: "\2194"; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); color: #fff; font-size: 16px; z-index: 1; }
  .slider-label { position: absolute; top: 10px; padding: 4px 10px; background: rgba(0,0,0,0.6); color: #fff; font-size: 11px; border-radius: 4px; z-index: 5; pointer-events: none; }
  .slider-label-left { left: 10px; }
  .slider-label-right { right: 10px; }
  .side-by-side { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .side-by-side .img-container { border: 1px solid #eee; border-radius: 4px; overflow: hidden; }
  .side-by-side .img-label { font-size: 12px; font-weight: 500; padding: 8px 12px; background: #f5f5f5; color: #666; }
  .side-by-side img { display: block; width: 100%; height: auto; }
  .diff-overlay img { display: block; max-width: 100%; height: auto; border: 1px solid #eee; border-radius: 4px; }
  .single-image img { display: block; max-width: 100%; height: auto; border: 1px solid #eee; border-radius: 4px; }
  .unchanged-section { margin-top: 32px; }
  .unchanged-toggle { cursor: pointer; font-size: 14px; color: #666; padding: 12px 0; }
  .unchanged-toggle:hover { color: #333; }
  .unchanged-list { display: none; }
  .unchanged-list.open { display: block; }
  .unchanged-item { padding: 8px 0; font-size: 13px; color: #888; border-bottom: 1px solid #f0f0f0; }
</style>
</head>
<body>

<div class="header">
  <h1>Visual Regression Report</h1>
  <p>{{.TotalCount}} screenshot{{if ne .TotalCount 1}}s{{end}} compared</p>
</div>

<div class="summary">
  {{if gt .ChangedCount 0}}<div class="summary-card summary-changed">{{.ChangedCount}} Changed</div>{{end}}
  {{if gt .AddedCount 0}}<div class="summary-card summary-added">{{.AddedCount}} Added</div>{{end}}
  {{if gt .RemovedCount 0}}<div class="summary-card summary-removed">{{.RemovedCount}} Removed</div>{{end}}
  <div class="summary-card summary-unchanged">{{.UnchangedCount}} Unchanged</div>
</div>

<div class="content">
{{if not .HasDifferences}}
  <div class="no-changes">
    <h2>No visual changes detected</h2>
    <p>All {{.TotalCount}} screenshots match their baselines.</p>
  </div>
{{end}}

{{range .Entries}}
{{if eq .Status "changed"}}
<div class="card">
  <div class="card-header">
    <span class="card-name">{{.Name}}</span>
    <span class="card-badge badge-changed">{{.DiffPercent}} changed</span>
  </div>
  <div class="tabs">
    <div class="tab active" onclick="switchTab(this, 'slider')">Slider</div>
    <div class="tab" onclick="switchTab(this, 'sidebyside')">Side by Side</div>
    <div class="tab" onclick="switchTab(this, 'diff')">Diff Overlay</div>
  </div>
  <div class="tab-content active" data-tab="slider">
    <div class="slider-container" onmousedown="startSlider(event, this)" onmousemove="moveSlider(event, this)" ontouchstart="startSlider(event, this)" ontouchmove="moveSlider(event, this)">
      <img src="{{.CurrentDataURI}}" alt="Current" draggable="false">
      <div class="slider-baseline">
        <img src="{{.BaselineDataURI}}" alt="Baseline" draggable="false">
      </div>
      <div class="slider-divider" style="left: calc(50% - 1.5px);"></div>
      <span class="slider-label slider-label-left">Baseline</span>
      <span class="slider-label slider-label-right">Current</span>
    </div>
  </div>
  <div class="tab-content" data-tab="sidebyside">
    <div class="side-by-side">
      <div class="img-container">
        <div class="img-label">Baseline</div>
        <img src="{{.BaselineDataURI}}" alt="Baseline">
      </div>
      <div class="img-container">
        <div class="img-label">Current</div>
        <img src="{{.CurrentDataURI}}" alt="Current">
      </div>
    </div>
  </div>
  <div class="tab-content" data-tab="diff">
    <div class="diff-overlay">
      {{if .HasDiff}}<img src="{{.DiffDataURI}}" alt="Diff overlay">{{end}}
    </div>
  </div>
</div>
{{end}}

{{if eq .Status "added"}}
<div class="card">
  <div class="card-header">
    <span class="card-name">{{.Name}}</span>
    <span class="card-badge badge-added">added</span>
  </div>
  <div class="tab-content active" data-tab="single">
    <div class="single-image">
      {{if .HasCurrent}}<img src="{{.CurrentDataURI}}" alt="New screenshot">{{end}}
    </div>
  </div>
</div>
{{end}}

{{if eq .Status "removed"}}
<div class="card">
  <div class="card-header">
    <span class="card-name">{{.Name}}</span>
    <span class="card-badge badge-removed">removed</span>
  </div>
  <div class="tab-content active" data-tab="single">
    <div class="single-image">
      {{if .HasBaseline}}<img src="{{.BaselineDataURI}}" alt="Removed screenshot">{{end}}
    </div>
  </div>
</div>
{{end}}
{{end}}

{{if gt .UnchangedCount 0}}
<div class="unchanged-section">
  <div class="unchanged-toggle" onclick="toggleUnchanged(this)">
    &#9654; {{.UnchangedCount}} unchanged screenshot{{if ne .UnchangedCount 1}}s{{end}} (click to expand)
  </div>
  <div class="unchanged-list">
    {{range .Entries}}{{if eq .Status "unchanged"}}<div class="unchanged-item">{{.Name}}</div>{{end}}{{end}}
  </div>
</div>
{{end}}

</div>

<script>
// Tab switching
function switchTab(tabEl, tabName) {
  const card = tabEl.closest('.card');
  card.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  card.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  tabEl.classList.add('active');
  card.querySelector('[data-tab="' + tabName + '"]').classList.add('active');
}

// Slider interaction
let sliderActive = false;

function startSlider(e, container) {
  sliderActive = true;
  moveSlider(e, container);
  const stopSlider = function() { sliderActive = false; };
  document.addEventListener('mouseup', stopSlider, { once: true });
  document.addEventListener('touchend', stopSlider, { once: true });
}

function moveSlider(e, container) {
  if (!sliderActive) return;
  e.preventDefault();
  const rect = container.getBoundingClientRect();
  const clientX = e.touches ? e.touches[0].clientX : e.clientX;
  let x = clientX - rect.left;
  x = Math.max(0, Math.min(x, rect.width));
  const percent = (x / rect.width) * 100;
  const clipRight = 100 - percent;
  container.querySelector('.slider-baseline').style.clipPath = 'inset(0 ' + clipRight + '% 0 0)';
  container.querySelector('.slider-divider').style.left = 'calc(' + percent + '% - 1.5px)';
}

// Unchanged section toggle
function toggleUnchanged(el) {
  const list = el.nextElementSibling;
  const isOpen = list.classList.toggle('open');
  el.innerHTML = (isOpen ? '&#9660;' : '&#9654;') + ' {{.UnchangedCount}} unchanged screenshot{{if ne .UnchangedCount 1}}s{{end}} (click to ' + (isOpen ? 'collapse' : 'expand') + ')';
}
</script>
</body>
</html>`
