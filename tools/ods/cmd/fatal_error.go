package cmd

import "fmt"

// fatalErrorf builds an error whose text is the capitalized line a command
// logs with log.Fatal before it exits. It keeps the log messages unchanged.
func fatalErrorf(format string, args ...any) error {
	return fmt.Errorf(format, args...)
}
