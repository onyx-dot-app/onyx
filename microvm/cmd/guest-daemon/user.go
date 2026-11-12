package main

import (
	"os/user"
	"strconv"
	"syscall"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/files"
)

// Env defaults when the image has no passwd entry for the command user.
const (
	fallbackHome = "/home/onyx"
	fallbackName = "sandbox"
)

// account is the passwd and group data of a uid; empty fields when unknown.
type account struct {
	name, home string
	groups     []string // supplementary gids
}

func lookupAccount(uid int) account {
	u, err := user.LookupId(strconv.Itoa(uid))
	if err != nil {
		return account{}
	}
	groups, err := u.GroupIds()
	if err != nil {
		groups = nil
	}
	return account{name: u.Username, home: u.HomeDir, groups: groups}
}

// commandIdentity is the user that commands run as, and its env.
type commandIdentity struct {
	cred *syscall.Credential
	env  map[string]string // HOME, USER, LOGNAME
}

// parseCommandUser reads --command-user ("uid:gid"). Empty: nil, commands
// run as the daemon (root).
func parseCommandUser(spec string, lookup func(uid int) account) (*commandIdentity, error) {
	owner, err := files.ParseOwner(spec)
	if err != nil || owner == nil {
		return nil, err
	}
	acct := lookup(owner.UID)
	cred := &syscall.Credential{Uid: uint32(owner.UID), Gid: uint32(owner.GID), Groups: []uint32{}}
	for _, g := range acct.groups {
		if gid, err := strconv.ParseUint(g, 10, 32); err == nil {
			cred.Groups = append(cred.Groups, uint32(gid))
		}
	}
	home, name := acct.home, acct.name
	if home == "" {
		home = fallbackHome
	}
	if name == "" {
		name = fallbackName
	}
	return &commandIdentity{cred: cred, env: map[string]string{"HOME": home, "USER": name, "LOGNAME": name}}, nil
}
