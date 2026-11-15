package postgres

import (
	"net"
	"net/url"
	"strings"
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

func IsLoopbackHost(host string) bool {
	host = strings.TrimSuffix(strings.TrimSpace(host), ".")
	if strings.EqualFold(host, "localhost") {
		return true
	}
	if strings.HasPrefix(host, "[") && strings.HasSuffix(host, "]") {
		host = host[1 : len(host)-1]
	}
	return net.ParseIP(host).IsLoopback()
}

// NewConfigFromEnvironment reads a private runtime environment without changing the process.
func NewConfigFromEnvironment(env []string) *Config {
	config := &Config{User: DefaultUser, Password: DefaultPassword, Host: DefaultHost, Port: DefaultPort, Database: DefaultDatabase}
	for _, entry := range env {
		key, value, ok := strings.Cut(entry, "=")
		if !ok || value == "" {
			continue
		}
		switch key {
		case "POSTGRES_USER":
			config.User = value
		case "POSTGRES_PASSWORD":
			config.Password = value
		case "POSTGRES_HOST":
			config.Host = value
		case "POSTGRES_PORT":
			config.Port = value
		case "POSTGRES_DB":
			config.Database = value
		}
	}
	return config
}

// ConnectionString returns a PostgreSQL connection string.
func (c *Config) ConnectionString() string {
	u := url.URL{
		Scheme: "postgresql",
		User:   url.UserPassword(c.User, c.Password),
		Host:   net.JoinHostPort(c.Host, c.Port),
		Path:   "/" + c.Database,
	}
	return u.String()
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
