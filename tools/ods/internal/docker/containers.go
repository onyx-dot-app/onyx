package docker

import (
	"encoding/json"
	"fmt"
	"os/exec"
	"strings"
	"time"
)

// Compose labels read from every container.
const (
	ComposeProjectLabel    = "com.docker.compose.project"
	ComposeServiceLabel    = "com.docker.compose.service"
	ComposeWorkingDirLabel = "com.docker.compose.project.working_dir"
)

// ComposeContainer is one container that belongs to a Compose project.
type ComposeContainer struct {
	ID         string
	Name       string
	Project    string
	Service    string
	WorkingDir string
	// State is the Docker state, such as "running" or "exited".
	State string
	// Health is the health check status, empty when there is no check.
	Health    string
	CreatedAt time.Time
	StartedAt time.Time
}

// Running reports whether the container is running.
func (c ComposeContainer) Running() bool { return c.State == "running" }

type inspectedContainer struct {
	ID      string    `json:"Id"`
	Name    string    `json:"Name"`
	Created time.Time `json:"Created"`
	State   struct {
		Status    string    `json:"Status"`
		StartedAt time.Time `json:"StartedAt"`
		Health    *struct {
			Status string `json:"Status"`
		} `json:"Health"`
	} `json:"State"`
	Config struct {
		Labels map[string]string `json:"Labels"`
	} `json:"Config"`
}

// ListComposeContainers returns every container, running or not, that has a
// Compose project label. It only reads from Docker.
func ListComposeContainers() ([]ComposeContainer, error) {
	out, err := exec.Command("docker", "ps", "-a", "-q", "--no-trunc", "--filter", "label="+ComposeProjectLabel).Output()
	if err != nil {
		return nil, fmt.Errorf("docker ps: %w", commandError(err))
	}
	ids := strings.Fields(string(out))
	if len(ids) == 0 {
		return nil, nil
	}
	out, err = exec.Command("docker", append([]string{"inspect", "--type", "container"}, ids...)...).Output()
	if err != nil {
		return nil, fmt.Errorf("docker inspect: %w", commandError(err))
	}
	return parseInspect(out)
}

func parseInspect(data []byte) ([]ComposeContainer, error) {
	var inspected []inspectedContainer
	if err := json.Unmarshal(data, &inspected); err != nil {
		return nil, fmt.Errorf("parse docker inspect: %w", err)
	}
	containers := make([]ComposeContainer, 0, len(inspected))
	for _, c := range inspected {
		labels := c.Config.Labels
		if labels[ComposeProjectLabel] == "" {
			continue
		}
		container := ComposeContainer{
			ID:         c.ID,
			Name:       strings.TrimPrefix(c.Name, "/"),
			Project:    labels[ComposeProjectLabel],
			Service:    labels[ComposeServiceLabel],
			WorkingDir: labels[ComposeWorkingDirLabel],
			State:      c.State.Status,
			CreatedAt:  c.Created,
			StartedAt:  c.State.StartedAt,
		}
		if c.State.Health != nil {
			container.Health = c.State.Health.Status
		}
		containers = append(containers, container)
	}
	return containers, nil
}

func commandError(err error) error {
	if exitErr, ok := err.(*exec.ExitError); ok && len(exitErr.Stderr) > 0 {
		return fmt.Errorf("%w: %s", err, strings.TrimSpace(string(exitErr.Stderr)))
	}
	return err
}
