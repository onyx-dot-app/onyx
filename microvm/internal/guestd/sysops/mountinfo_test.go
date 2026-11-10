package sysops

import "testing"

func TestMountedOn(t *testing.T) {
	info := "22 1 254:0 / / ro,relatime - ext4 /dev/vda ro\n" +
		"40 22 254:2 / /workspace/managed ro,nodev - ext4 /dev/vdc ro\n" +
		"41 40 254:5 / /workspace/managed ro,nodev - ext4 /dev/vdf ro\n"
	for _, c := range []struct {
		mp    string
		major uint32
		minor uint32
		want  bool
	}{
		{"/workspace/managed", 254, 2, true},
		{"/workspace/managed", 254, 5, true},
		{"/workspace/managed", 254, 0, false},
		{"/workspace", 254, 2, false},
	} {
		if got := mountedOn(info, c.mp, c.major, c.minor); got != c.want {
			t.Errorf("%s %d:%d = %v, want %v", c.mp, c.major, c.minor, got, c.want)
		}
	}
}
