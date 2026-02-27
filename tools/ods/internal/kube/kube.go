package kube

import (
	"bytes"
	"fmt"
	"os/exec"
	"strings"

	log "github.com/sirupsen/logrus"
)

// UseCluster switches kubectl context to the given EKS cluster and namespace.
func UseCluster(clusterName, region, namespace string) error {
	log.Debugf("Switching kubectl context to %s (region=%s, namespace=%s)", clusterName, region, namespace)

	cmd := exec.Command("aws", "eks", "update-kubeconfig", "--region", region, "--name", clusterName)
	if out, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("aws eks update-kubeconfig failed: %w\n%s", err, string(out))
	}

	cmd = exec.Command("kubectl", "config", "set-context", "--current", "--namespace="+namespace)
	if out, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("kubectl set-context failed: %w\n%s", err, string(out))
	}

	return nil
}

// FindPod returns the name of the first pod matching the given substring.
func FindPod(substring string) (string, error) {
	cmd := exec.Command("kubectl", "get", "po", "--no-headers", "-o", "custom-columns=NAME:.metadata.name")
	out, err := cmd.Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return "", fmt.Errorf("kubectl get po failed: %w\n%s", err, string(exitErr.Stderr))
		}
		return "", fmt.Errorf("kubectl get po failed: %w", err)
	}

	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		name := strings.TrimSpace(line)
		if strings.Contains(name, substring) {
			log.Debugf("Found pod: %s", name)
			return name, nil
		}
	}

	return "", fmt.Errorf("no pod found matching %q", substring)
}

// ExecOnPod runs a command on a pod and returns its stdout.
func ExecOnPod(pod string, command ...string) (string, error) {
	args := append([]string{"exec", pod, "--"}, command...)
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
