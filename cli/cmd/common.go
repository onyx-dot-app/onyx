package cmd

import (
	"errors"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
)

func requireConfig() (config.OnyxCliConfig, error) {
	cfg := config.Load()
	if !cfg.IsConfigured() {
		return cfg, exitcodes.New(exitcodes.NotConfigured,
			"onyx CLI is not configured\n  Set ONYX_PAT (personal access token) or run: onyx-cli configure")
	}
	return cfg, nil
}

func requireClient() (config.OnyxCliConfig, *api.Client, error) {
	cfg, err := requireConfig()
	if err != nil {
		return cfg, nil, err
	}
	return cfg, api.NewClient(cfg), nil
}

func apiErrorToExit(err error, action string) error {
	var authErr *api.AuthError
	if errors.As(err, &authErr) {
		return exitcodes.Newf(exitcodes.AuthFailure, "%s: %v", action, err)
	}
	var apiErr *api.OnyxAPIError
	if errors.As(err, &apiErr) {
		return exitcodes.Newf(exitcodes.ForHTTPStatus(apiErr.StatusCode), "%s: %s", action, apiErr.Error())
	}
	return exitcodes.Newf(exitcodes.Unreachable, "%s: %v", action, err)
}
