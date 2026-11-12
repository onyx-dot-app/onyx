package audit

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

const grypeImage = "anchore/grype:v0.121.1@sha256:6b06708b036f74b2cd70e94b706b4586af96d1932e6ac46255940b2e39dd44a9"

// ScanSBOM scans an explicit inventory for software outside package managers.
// The inventory must exist in the image; a failed extraction never means clean.
func ScanSBOM(image, inventory string, stderr io.Writer, policy UpdatePolicy) (*Result, error) {
	directory, err := os.MkdirTemp("", "ods-sbom-*")
	if err != nil {
		return nil, err
	}
	defer func() { _ = os.RemoveAll(directory) }()
	create := exec.Command("docker", "create", "--entrypoint", "/bin/true", image)
	create.Stderr = stderr
	output, err := create.Output()
	if err != nil {
		return nil, fmt.Errorf("create inventory container: %w", err)
	}
	container := strings.TrimSpace(string(output))
	defer func() { _ = exec.Command("docker", "rm", container).Run() }()
	copy := exec.Command("docker", "cp", container+":"+inventory, filepath.Join(directory, "inventory.json"))
	copy.Stderr = stderr
	if err := copy.Run(); err != nil {
		return nil, fmt.Errorf("extract required SBOM %s: %w", inventory, err)
	}
	data, err := os.ReadFile(filepath.Join(directory, "inventory.json"))
	if err != nil {
		return nil, err
	}
	var inventoryData struct {
		Components []struct {
			Type       string            `json:"type"`
			Name       string            `json:"name"`
			Version    string            `json:"version"`
			CPE        string            `json:"cpe"`
			PURL       string            `json:"purl"`
			BOMRef     string            `json:"bom-ref"`
			Group      string            `json:"group"`
			Properties []json.RawMessage `json:"properties"`
		} `json:"components"`
	}
	if err := json.Unmarshal(data, &inventoryData); err != nil {
		return nil, err
	}
	if len(inventoryData.Components) == 0 {
		return nil, fmt.Errorf("required SBOM has no components")
	}
	var updates []UpdateStatus
	var packages []ScannedPackage
	for _, component := range inventoryData.Components {
		switch component.Type {
		case "application", "framework", "library", "machine-learning-model", "firmware":
		default:
			return nil, fmt.Errorf("unsupported SBOM package type %q", component.Type)
		}
		if component.Name == "" || component.Version == "" || component.CPE == "" {
			return nil, fmt.Errorf("SBOM component requires name, version and CPE")
		}
		cpe := strings.Split(component.CPE, ":")
		if len(cpe) != 13 || cpe[0] != "cpe" || cpe[1] != "2.3" || cpe[4] != component.Name || cpe[5] != component.Version {
			return nil, fmt.Errorf("SBOM CPE must identify the component name and installed version")
		}
		// Grype reports UnknownPackage for CPE-only inventories without package metadata.
		// Leave other identities unclaimed rather than close an unrelated alert.
		if component.PURL == "" && !strings.HasPrefix(component.BOMRef, "pkg:") && component.Group == "" && len(component.Properties) == 0 {
			packages = append(packages, ScannedPackage{Ecosystem: "UnknownPackage", Package: component.Name})
		}
		if policy != nil {
			if _, ok := policy[component.Name]; !ok {
				return nil, fmt.Errorf("missing update policy for %s", component.Name)
			}
		}
		if entry, ok := policy[component.Name]; ok {
			status, err := CheckUpdate(component.Name, component.Version, entry, time.Now())
			if err != nil {
				return nil, err
			}
			updates = append(updates, status)
		}
	}
	args := []string{"run", "--rm", "--env", "GRYPE_CHECK_FOR_APP_UPDATE=false", "--mount", "type=bind,source=" + directory + ",target=/inventory,readonly"}
	if ca := os.Getenv("SSL_CERT_FILE"); ca != "" {
		args = append(args, "--mount", "type=bind,source="+ca+",target=/certs/ca.pem,readonly", "--env", "SSL_CERT_FILE=/certs/ca.pem")
	}
	registry := os.Getenv("BASE_IMAGE_REGISTRY")
	if registry == "" {
		registry = "docker.io"
	}
	args = append(args, registry+"/"+grypeImage, "sbom:/inventory/inventory.json", "--output", "json")
	scan := exec.Command("docker", args...)
	scan.Stderr = stderr
	output, err = scan.Output()
	if err != nil {
		return nil, fmt.Errorf("scan required SBOM %s: %w", inventory, err)
	}
	findings, err := grypeFindings(output, image+":"+inventory)
	if err != nil {
		return nil, err
	}
	return &Result{Findings: findings, Updates: updates, ScannedPackages: packages}, nil
}

func grypeFindings(data []byte, manifest string) ([]Finding, error) {
	var report struct {
		Matches *[]struct {
			Vulnerability struct {
				ID          string `json:"id"`
				Severity    string `json:"severity"`
				Description string `json:"description"`
				DataSource  string `json:"dataSource"`
				Fix         struct {
					Versions []string `json:"versions"`
				} `json:"fix"`
			} `json:"vulnerability"`
			RelatedVulnerabilities []struct {
				ID string `json:"id"`
			} `json:"relatedVulnerabilities"`
			Artifact struct {
				Name    string `json:"name"`
				Version string `json:"version"`
				Type    string `json:"type"`
			} `json:"artifact"`
		} `json:"matches"`
	}
	if err := json.Unmarshal(data, &report); err != nil {
		return nil, err
	}
	if report.Matches == nil {
		return nil, fmt.Errorf("grype report has no matches array")
	}
	findings := make([]Finding, 0, len(*report.Matches))
	for _, match := range *report.Matches {
		v, a := match.Vulnerability, match.Artifact
		if v.ID == "" || a.Name == "" {
			return nil, fmt.Errorf("incomplete Grype match")
		}
		var aliases []string
		for _, related := range match.RelatedVulnerabilities {
			aliases = append(aliases, related.ID)
		}
		findings = append(findings, Finding{Aliases: aliases, ID: v.ID, Ecosystem: a.Type, Package: a.Name, Version: a.Version,
			Severity: ParseSeverity(v.Severity), Title: v.Description, URL: v.DataSource, Source: "grype-sbom",
			FixedIn: strings.Join(v.Fix.Versions, ", "), Manifest: manifest})
	}
	return findings, nil
}
