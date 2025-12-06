package postgres

import (
	"fmt"
	"net/url"
	"os"
)

// Config holds PostgreSQL connection configuration.
type Config struct {
	User     string
	Password string
	Host     string
	Port     string
	Database string
}

// Default values for PostgreSQL connection
const (
	DefaultUser     = "postgres"
	DefaultPassword = "password"
	DefaultHost     = "localhost"
	DefaultPort     = "5432"
	DefaultDatabase = "postgres"
)

// NewConfigFromEnv creates a Config from environment variables with defaults.
func NewConfigFromEnv() *Config {
	return &Config{
		User:     getEnvOrDefault("POSTGRES_USER", DefaultUser),
		Password: getEnvOrDefault("POSTGRES_PASSWORD", DefaultPassword),
		Host:     getEnvOrDefault("POSTGRES_HOST", DefaultHost),
		Port:     getEnvOrDefault("POSTGRES_PORT", DefaultPort),
		Database: getEnvOrDefault("POSTGRES_DB", DefaultDatabase),
	}
}

// getEnvOrDefault returns the environment variable value or a default.
func getEnvOrDefault(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

// ConnectionString returns a PostgreSQL connection string.
func (c *Config) ConnectionString() string {
	return fmt.Sprintf("postgresql://%s:%s@%s:%s/%s",
		url.QueryEscape(c.User), url.QueryEscape(c.Password), c.Host, c.Port, c.Database)
}

// PgDumpArgs returns common arguments for pg_dump.
func (c *Config) PgDumpArgs(format string) []string {
	args := []string{
		"-U", c.User,
		"-d", c.Database,
	}
	if format == "custom" {
		args = append(args, "-Fc")
	} else {
		args = append(args, "-Fp")
	}
	return args
}

// PgRestoreArgs returns common arguments for pg_restore.
func (c *Config) PgRestoreArgs() []string {
	return []string{
		"-U", c.User,
		"-d", c.Database,
	}
}

// PsqlArgs returns common arguments for psql.
func (c *Config) PsqlArgs() []string {
	return []string{
		"-U", c.User,
		"-d", c.Database,
	}
}

// Env returns environment variables for PostgreSQL commands.
func (c *Config) Env() map[string]string {
	return map[string]string{
		"PGPASSWORD": c.Password,
	}
}
