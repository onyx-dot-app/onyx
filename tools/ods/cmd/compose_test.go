package cmd

import "testing"

func TestCheckComposeOptions(t *testing.T) {
	tests := []struct {
		name    string
		profile string
		noEE    bool
		wantErr bool
	}{
		{name: "default profile with EE", profile: "", noEE: false, wantErr: false},
		{name: "default profile without EE", profile: "", noEE: true, wantErr: false},
		{name: "dev profile without EE", profile: "dev", noEE: true, wantErr: false},
		{name: "multitenant profile with EE", profile: "multitenant", noEE: false, wantErr: false},
		{name: "multitenant profile without EE", profile: "multitenant", noEE: true, wantErr: true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := checkComposeOptions(tt.profile, &ComposeOptions{NoEE: tt.noEE})
			if (err != nil) != tt.wantErr {
				t.Fatalf("checkComposeOptions(%q, NoEE=%v) error = %v, wantErr %v", tt.profile, tt.noEE, err, tt.wantErr)
			}
		})
	}
}
