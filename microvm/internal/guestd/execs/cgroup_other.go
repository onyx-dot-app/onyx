//go:build !linux

package execs

import "errors"

// Cgroups needs Linux. On other systems NewCgroups fails; use ProcessGroups.
type Cgroups struct {
	Root string
}

// NewCgroups fails on this platform.
func NewCgroups(string) (*Cgroups, error) {
	return nil, errors.New("cgroups need Linux")
}

// NewGroup implements Isolator.
func (c *Cgroups) NewGroup(string) (Group, error) { return nil, errors.New("cgroups need Linux") }
