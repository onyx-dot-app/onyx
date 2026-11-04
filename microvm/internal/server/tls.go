package server

import (
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"os"

	"google.golang.org/grpc/credentials"
)

// MTLSConfig is the TLS config of the TCP listener: the agent's own cert,
// and only client certificates that chain to the api_server CA (D2).
func MTLSConfig(certFile, keyFile, clientCAFile string) (*tls.Config, error) {
	cert, err := tls.LoadX509KeyPair(certFile, keyFile)
	if err != nil {
		return nil, fmt.Errorf("load server cert: %w", err)
	}
	raw, err := os.ReadFile(clientCAFile)
	if err != nil {
		return nil, fmt.Errorf("read client CA: %w", err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(raw) {
		return nil, errors.New("client CA file has no PEM certificate")
	}
	return &tls.Config{
		Certificates: []tls.Certificate{cert},
		ClientAuth:   tls.RequireAndVerifyClientCert,
		ClientCAs:    pool,
		MinVersion:   tls.VersionTLS13,
	}, nil
}

// MTLSCredentials wraps MTLSConfig for a gRPC server.
func MTLSCredentials(certFile, keyFile, clientCAFile string) (credentials.TransportCredentials, error) {
	cfg, err := MTLSConfig(certFile, keyFile, clientCAFile)
	if err != nil {
		return nil, err
	}
	return credentials.NewTLS(cfg), nil
}
