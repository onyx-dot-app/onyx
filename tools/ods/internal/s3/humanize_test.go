package s3

import "testing"

func TestS3URL_HTTPEndpoint(t *testing.T) {
	parsed, err := ParseS3URL("s3://my-bucket/coverage/tools-ods/abc.yaml")
	if err != nil {
		t.Fatalf("ParseS3URL failed: %v", err)
	}

	got := parsed.HTTPEndpoint()

	want := "https://my-bucket.s3.amazonaws.com/coverage/tools-ods/abc.yaml"
	if got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestHumanizeBytes(t *testing.T) {
	const kib int64 = 1024

	tests := []struct {
		bytes int64
		want  string
	}{
		{bytes: 0, want: "0 B"},
		{bytes: 512, want: "512 B"},
		{bytes: kib - 1, want: "1023 B"},
		{bytes: kib, want: "1.0 KB"},
		{bytes: kib + kib/2, want: "1.5 KB"},
		{bytes: kib * kib, want: "1.0 MB"},
		{bytes: 5 * kib * kib * kib, want: "5.0 GB"},
	}
	for _, tt := range tests {
		if got := humanizeBytes(tt.bytes); got != tt.want {
			t.Errorf("humanizeBytes(%d) = %q, want %q", tt.bytes, got, tt.want)
		}
	}
}
