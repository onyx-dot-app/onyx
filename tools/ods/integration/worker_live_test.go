//go:build integration

package integration

import (
	"bytes"
	"encoding/json"
	"io"
	"mime/multipart"
	"net/http"
	"net/textproto"
	"net/url"
	"os"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
)

type liveUserFile struct {
	ID         string `json:"id"`
	Status     string `json:"status"`
	ChunkCount *int   `json:"chunk_count"`
}

func TestStackLiveUserFileWorker(t *testing.T) {
	if os.Getenv("ODS_STACK_LIVE_WORKERS") != "1" {
		t.Skip("set ODS_STACK_LIVE_WORKERS=1 after the live lifecycle test seeds the admin account")
	}
	stack := configuredStack(t, "ODS_STACK_LIVE_ROOT_B")
	data, err := stack.command("stack", "up", "--profile", "default", "--skip-prepare", "--timeout", "12m", "--json")
	if err != nil {
		t.Fatal(err)
	}
	var status devstack.Status
	if err := json.Unmarshal(data, &status); err != nil {
		t.Fatalf("invalid lifecycle JSON: %v", err)
	}
	if !status.Ready || status.Profile != "default" {
		t.Fatalf("default stack is not ready: phase=%s errors=%v", status.Phase, status.Errors)
	}
	workerRunning := false
	for _, service := range status.Services {
		if service.Name == "Celery user_file_processing" && service.State == devstack.StateRunning {
			workerRunning = true
		}
	}
	if !workerRunning {
		t.Fatal("default stack has no running user-file worker")
	}
	if code := stack.login(t, &status, "admin_user@example.com"); code != http.StatusNoContent {
		t.Fatalf("seeded admin login: HTTP %d", code)
	}
	base := status.URLs["web"]
	if base == "" {
		t.Fatal("stack status has no frontend URL")
	}
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	header := make(textproto.MIMEHeader)
	header.Set("Content-Disposition", `form-data; name="files"; filename="ods-worker-proof.txt"`)
	header.Set("Content-Type", "text/plain")
	part, err := writer.CreatePart(header)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := io.WriteString(part, "ODS live worker validation: a small document must pass through Celery and the real indexing pipeline."); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	response, err := stack.client.Post(base+"/api/user/projects/file/upload", writer.FormDataContentType(), &body)
	if err != nil {
		t.Fatal(err)
	}
	var upload struct {
		UserFiles     []liveUserFile `json:"user_files"`
		RejectedFiles []struct {
			FileName string `json:"file_name"`
			Reason   string `json:"reason"`
		} `json:"rejected_files"`
	}
	decodeLiveJSON(t, response, http.StatusOK, &upload)
	if len(upload.UserFiles) != 1 || upload.UserFiles[0].ID == "" || len(upload.RejectedFiles) != 0 {
		t.Fatalf("upload did not accept one text document: %+v", upload)
	}
	fileID := upload.UserFiles[0].ID
	fileURL := base + "/api/user/projects/file/" + url.PathEscape(fileID)
	t.Cleanup(func() {
		request, err := http.NewRequest(http.MethodDelete, fileURL, nil)
		if err != nil {
			t.Error(err)
			return
		}
		response, err := stack.client.Do(request)
		if err != nil {
			t.Errorf("delete validation file: %v", err)
			return
		}
		var deletion struct {
			HasAssociations bool `json:"has_associations"`
		}
		decodeLiveJSON(t, response, http.StatusOK, &deletion)
		if deletion.HasAssociations {
			t.Error("validation file acquired associations and could not be deleted")
		}
	})
	deadline := time.Now().Add(8 * time.Minute)
	previousStatus := ""
	for time.Now().Before(deadline) {
		response, err := stack.client.Get(fileURL)
		if err != nil {
			t.Fatal(err)
		}
		var file liveUserFile
		decodeLiveJSON(t, response, http.StatusOK, &file)
		if file.ID != fileID {
			t.Fatalf("poll returned another file: %q", file.ID)
		}
		if file.Status != previousStatus {
			t.Logf("user file %s: %s", fileID, file.Status)
			previousStatus = file.Status
		}
		switch file.Status {
		case "COMPLETED":
			if file.ChunkCount == nil || *file.ChunkCount <= 0 {
				t.Fatalf("completed file has no indexed chunks: %+v", file)
			}
			t.Logf("user-file worker indexed %d chunks", *file.ChunkCount)
			return
		case "FAILED", "CANCELED", "SKIPPED":
			t.Fatalf("user-file processing did not index the document: %s", file.Status)
		}
		time.Sleep(2 * time.Second)
	}
	t.Fatalf("user-file indexing did not complete within 8m; last status=%s", previousStatus)
}

func decodeLiveJSON(t *testing.T, response *http.Response, wantStatus int, value any) {
	t.Helper()
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != wantStatus {
		body, err := io.ReadAll(io.LimitReader(response.Body, 4096))
		if err != nil {
			t.Fatal(err)
		}
		t.Fatalf("%s %s: HTTP %d, want %d: %s", response.Request.Method, response.Request.URL.Path, response.StatusCode, wantStatus, body)
	}
	if err := json.NewDecoder(response.Body).Decode(value); err != nil {
		t.Fatalf("invalid response JSON: %v", err)
	}
}
