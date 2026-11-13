package template

import "os"

// fingerprint identifies one version of a file without reading it. A write,
// truncate, chmod, chown or replace changes it (ctime), so a changed file is
// hashed again before its next use.
type fingerprint struct {
	dev, ino     uint64
	size         int64
	mtime, ctime int64
	mode         os.FileMode
}

func statPrint(path string) (fingerprint, error) {
	st, err := os.Lstat(path)
	if err != nil {
		return fingerprint{}, err
	}
	p := fingerprint{size: st.Size(), mtime: st.ModTime().UnixNano(), mode: st.Mode()}
	sysPrint(st, &p)
	return p, nil
}
