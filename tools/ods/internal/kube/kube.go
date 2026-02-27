package kube

import (
	"bytes"
	"fmt"
	"os/exec"
	"strings"

	log "github.com/sirupsen/logrus"
)

// Cluster holds the connection info for a Kubernetes cluster.
type Cluster struct {
	Name      string
	Region    string
	Namespace string
}

// EnsureContext makes sure the cluster exists in kubeconfig, calling
// aws eks update-kubeconfig only if the context is missing.
func (c *Cluster) EnsureContext() error {
	// Check if context already exists in kubeconfig
	cmd := exec.Command("kubectl", "config", "get-contexts", c.Name, "--no-headers")
	if err := cmd.Run(); err == nil {
		log.Debugf("Context %s already exists, skipping aws eks update-kubeconfig", c.Name)
		return nil
	}

	log.Infof("Context %s not found, fetching kubeconfig from AWS...", c.Name)
	cmd = exec.Command("aws", "eks", "update-kubeconfig", "--region", c.Region, "--name", c.Name, "--alias", c.Name)
	if out, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("aws eks update-kubeconfig failed: %w\n%s", err, string(out))
	}

	return nil
}

// kubectlArgs returns common kubectl flags to target this cluster without mutating global context.
func (c *Cluster) kubectlArgs() []string {
	return []string{"--context", c.Name, "--namespace", c.Namespace}
}

// FindPod returns the name of the first Running/Ready pod matching the given substring.
func (c *Cluster) FindPod(substring string) (string, error) {
	args := append(c.kubectlArgs(), "get", "po",
		"--field-selector", "status.phase=Running",
		"--no-headers",
		"-o", "custom-columns=NAME:.metadata.name,READY:.status.conditions[?(@.type=='Ready')].status",
	)
	cmd := exec.Command("kubectl", args...)
	out, err := cmd.Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return "", fmt.Errorf("kubectl get po failed: %w\n%s", err, string(exitErr.Stderr))
		}
		return "", fmt.Errorf("kubectl get po failed: %w", err)
	}

	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		name, ready := fields[0], fields[1]
		if strings.Contains(name, substring) && ready == "True" {
			log.Debugf("Found pod: %s", name)
			return name, nil
		}
	}

	return "", fmt.Errorf("no ready pod found matching %q", substring)
}

// ExecOnPod runs a command on a pod and returns its stdout.
func (c *Cluster) ExecOnPod(pod string, command ...string) (string, error) {
	args := append(c.kubectlArgs(), "exec", pod, "--")
	args = append(args, command...)
	log.Debugf("Running: kubectl %s", strings.Join(args, " "))

	cmd := exec.Command("kubectl", args...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("kubectl exec failed: %w\n%s", err, stderr.String())
	}

	return stdout.String(), nil
}
