package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestMCPHandlers(t *testing.T) {
	// Setup: Create a real temporary workspace
	tempDir := t.TempDir()
	rootDir, err := os.OpenRoot(tempDir)
	if err != nil {
		t.Fatalf("Failed to open root: %v", err)
	}
	defer rootDir.Close()

	token := "secret-test-token"

	// Helper to create authenticated requests
	newAuthRequest := func(method, url string, body io.Reader) *http.Request {
		req := httptest.NewRequest(method, url, body)
		req.Header.Set("Authorization", "Bearer "+token)
		return req
	}

	t.Run("Create results in Empty File", func(t *testing.T) {
		// 1. Create the file
		filename := "empty_check.txt"
		req := newAuthRequest("POST", "/create?path="+filename, nil)
		rr := httptest.NewRecorder()
		handleCreate(rootDir, token)(rr, req)

		if rr.Code != http.StatusCreated {
			t.Fatalf("Failed to create file: %v", rr.Code)
		}

		// 2. Verify size on disk is exactly 0
		info, err := os.Stat(filepath.Join(tempDir, filename))
		if err != nil {
			t.Fatalf("File does not exist on disk: %v", err)
		}
		if info.Size() != 0 {
			t.Errorf("Expected empty file (0 bytes), but got %d bytes", info.Size())
		}
	})

	t.Run("Read returns Exact Content", func(t *testing.T) {
		// 1. Manually write a file to the temp workspace
		filename := "read_test.txt"
		expectedContent := "This is a secret message for the agent."
		err := os.WriteFile(filepath.Join(tempDir, filename), []byte(expectedContent), 0644)
		if err != nil {
			t.Fatalf("Setup failed: %v", err)
		}

		// 2. Call the /read handler
		req := newAuthRequest("GET", "/read?path="+filename, nil)
		rr := httptest.NewRecorder()
		handleRead(rootDir, token)(rr, req)

		// 3. Verify HTTP response
		if rr.Code != http.StatusOK {
			t.Fatalf("Read handler returned status %v", rr.Code)
		}

		// 4. Verify the Body matches exactly
		gotContent := rr.Body.String()
		if gotContent != expectedContent {
			t.Errorf("Content mismatch!\nWant: %q\nGot:  %q", expectedContent, gotContent)
		}
	})

	t.Run("Write and Overwrite", func(t *testing.T) {
		payload := map[string]string{
			"path":    "data.txt",
			"content": "initial content",
		}
		body, _ := json.Marshal(payload)

		req := newAuthRequest("POST", "/write", bytes.NewBuffer(body))
		rr := httptest.NewRecorder()
		handleWrite(rootDir, token)(rr, req)

		if rr.Code != http.StatusOK {
			t.Fatalf("Write failed: %v", rr.Body.String())
		}

		// Verify disk content
		got, _ := os.ReadFile(filepath.Join(tempDir, "data.txt"))
		if string(got) != "initial content" {
			t.Errorf("Expected 'initial content', got '%s'", string(got))
		}
	})

	t.Run("Recursive List", func(t *testing.T) {
		// Create a nested structure
		os.MkdirAll(filepath.Join(tempDir, "a/b"), 0755)
		os.WriteFile(filepath.Join(tempDir, "a/b/c.txt"), []byte("test"), 0644)

		req := newAuthRequest("GET", "/list", nil)
		rr := httptest.NewRecorder()
		handleList(rootDir, token)(rr, req)

		var resp map[string]interface{}
		json.Unmarshal(rr.Body.Bytes(), &resp)

		files := resp["files"].([]interface{})
		found := false
		for _, f := range files {
			if f.(string) == "a/b/c.txt" {
				found = true
			}
		}
		if !found {
			t.Errorf("List failed to find nested file. Got: %v", files)
		}
	})

	t.Run("Remove File", func(t *testing.T) {
		req := newAuthRequest("DELETE", "/remove?path=data.txt", nil)
		rr := httptest.NewRecorder()
		handleRemove(rootDir, token)(rr, req)

		if rr.Code != http.StatusOK {
			t.Errorf("Remove failed: %v", rr.Code)
		}

		if _, err := os.Stat(filepath.Join(tempDir, "data.txt")); !os.IsNotExist(err) {
			t.Error("File still exists after removal")
		}
	})

	t.Run("Security: Path Traversal Block", func(t *testing.T) {
		// Attempting to read outside the jail
		req := newAuthRequest("GET", "/read?path=../etc/passwd", nil)
		rr := httptest.NewRecorder()
		handleRead(rootDir, token)(rr, req)

		// os.OpenRoot should naturally prevent this
		if rr.Code == http.StatusOK {
			t.Error("Security Breach: Successfully read file outside of rootDir!")
		}
	})

	t.Run("Read: Missing file_path returns 400", func(t *testing.T) {
		// No path query parameter provided at all
		req := newAuthRequest("GET", "/read", nil)
		rr := httptest.NewRecorder()
		handleRead(rootDir, token)(rr, req)

		if rr.Code != http.StatusBadRequest {
			t.Errorf("Expected 400 Bad Request for missing file_path, got %d", rr.Code)
		}
	})

	t.Run("Read: Null byte in file_path returns 400", func(t *testing.T) {
		// path value contains a null byte (URL-encoded as %00)
		req := newAuthRequest("GET", "/read?path=evil%00file", nil)
		rr := httptest.NewRecorder()
		handleRead(rootDir, token)(rr, req)

		if rr.Code != http.StatusBadRequest {
			t.Errorf("Expected 400 Bad Request for null byte in file_path, got %d", rr.Code)
		}
	})

	t.Run("Read: Oversized file_path returns 400", func(t *testing.T) {
		// path value is 4097 bytes, which exceeds the 4096-byte limit
		longPath := strings.Repeat("a", 4097)
		req := newAuthRequest("GET", "/read?path="+longPath, nil)
		rr := httptest.NewRecorder()
		handleRead(rootDir, token)(rr, req)

		if rr.Code != http.StatusBadRequest {
			t.Errorf("Expected 400 Bad Request for oversized file_path, got %d", rr.Code)
		}
	})

	// ── Grep tests ────────────────────────────────────────────────────────────

	t.Run("Grep: happy path returns matching lines", func(t *testing.T) {
		// Write a file with known content
		err := os.WriteFile(filepath.Join(tempDir, "grep_target.txt"), []byte("hello world\nfoo bar\nhello again\n"), 0644)
		if err != nil {
			t.Fatalf("Setup failed: %v", err)
		}

		body, _ := json.Marshal(map[string]interface{}{
			"pattern": "hello",
		})
		req := newAuthRequest("POST", "/grep", bytes.NewBuffer(body))
		rr := httptest.NewRecorder()
		handleGrep(rootDir, token)(rr, req)

		if rr.Code != http.StatusOK {
			t.Fatalf("Grep returned status %d: %s", rr.Code, rr.Body.String())
		}

		var matches []map[string]interface{}
		if err := json.Unmarshal(rr.Body.Bytes(), &matches); err != nil {
			t.Fatalf("Failed to decode response: %v", err)
		}

		// Should find 2 lines containing "hello"
		if len(matches) != 2 {
			t.Errorf("Expected 2 matches, got %d: %v", len(matches), matches)
		}
		for _, m := range matches {
			if !strings.Contains(m["file"].(string), "grep_target.txt") {
				t.Errorf("Unexpected file in match: %v", m["file"])
			}
			if !strings.Contains(m["line"].(string), "hello") {
				t.Errorf("Match line does not contain 'hello': %v", m["line"])
			}
		}
	})

	t.Run("Grep: max_results truncates output", func(t *testing.T) {
		// File already exists with 2 "hello" lines from previous test.
		body, _ := json.Marshal(map[string]interface{}{
			"pattern":     "hello",
			"max_results": 1,
		})
		req := newAuthRequest("POST", "/grep", bytes.NewBuffer(body))
		rr := httptest.NewRecorder()
		handleGrep(rootDir, token)(rr, req)

		if rr.Code != http.StatusOK {
			t.Fatalf("Grep returned status %d", rr.Code)
		}

		var matches []map[string]interface{}
		json.Unmarshal(rr.Body.Bytes(), &matches)

		if len(matches) != 1 {
			t.Errorf("Expected exactly 1 match (max_results=1), got %d", len(matches))
		}
	})

	t.Run("Grep: no matches returns empty array", func(t *testing.T) {
		body, _ := json.Marshal(map[string]interface{}{
			"pattern": "ZZZNOMATCHZZZ",
		})
		req := newAuthRequest("POST", "/grep", bytes.NewBuffer(body))
		rr := httptest.NewRecorder()
		handleGrep(rootDir, token)(rr, req)

		if rr.Code != http.StatusOK {
			t.Fatalf("Grep returned status %d", rr.Code)
		}

		var matches []map[string]interface{}
		json.Unmarshal(rr.Body.Bytes(), &matches)

		if len(matches) != 0 {
			t.Errorf("Expected 0 matches, got %d", len(matches))
		}
	})

	t.Run("Grep: invalid pattern returns 400", func(t *testing.T) {
		body, _ := json.Marshal(map[string]interface{}{
			"pattern": "[invalid",
		})
		req := newAuthRequest("POST", "/grep", bytes.NewBuffer(body))
		rr := httptest.NewRecorder()
		handleGrep(rootDir, token)(rr, req)

		if rr.Code != http.StatusBadRequest {
			t.Errorf("Expected 400 for invalid pattern, got %d", rr.Code)
		}
	})

	// ── Replace tests ─────────────────────────────────────────────────────────

	t.Run("Replace: happy path replaces all occurrences", func(t *testing.T) {
		filename := "replace_me.txt"
		err := os.WriteFile(filepath.Join(tempDir, filename), []byte("cat cat cat dog"), 0644)
		if err != nil {
			t.Fatalf("Setup failed: %v", err)
		}

		body, _ := json.Marshal(map[string]string{
			"path":       filename,
			"old_string": "cat",
			"new_string": "bird",
		})
		req := newAuthRequest("POST", "/replace", bytes.NewBuffer(body))
		rr := httptest.NewRecorder()
		handleReplace(rootDir, token)(rr, req)

		if rr.Code != http.StatusOK {
			t.Fatalf("Replace returned status %d: %s", rr.Code, rr.Body.String())
		}

		var resp map[string]interface{}
		json.Unmarshal(rr.Body.Bytes(), &resp)

		if resp["replacements_made"].(float64) != 3 {
			t.Errorf("Expected 3 replacements, got %v", resp["replacements_made"])
		}

		// Verify disk content
		got, _ := os.ReadFile(filepath.Join(tempDir, filename))
		if string(got) != "bird bird bird dog" {
			t.Errorf("File content mismatch after replace: %q", string(got))
		}
	})

	t.Run("Replace: zero match returns 4xx", func(t *testing.T) {
		filename := "replace_me.txt" // already exists from previous test

		body, _ := json.Marshal(map[string]string{
			"path":       filename,
			"old_string": "ZZZNOMATCHZZZ",
			"new_string": "anything",
		})
		req := newAuthRequest("POST", "/replace", bytes.NewBuffer(body))
		rr := httptest.NewRecorder()
		handleReplace(rootDir, token)(rr, req)

		if rr.Code < 400 {
			t.Errorf("Expected 4xx when old_string not found, got %d", rr.Code)
		}
	})

	t.Run("Replace: path traversal rejected", func(t *testing.T) {
		body, _ := json.Marshal(map[string]string{
			"path":       "../etc/passwd",
			"old_string": "root",
			"new_string": "hacked",
		})
		req := newAuthRequest("POST", "/replace", bytes.NewBuffer(body))
		rr := httptest.NewRecorder()
		handleReplace(rootDir, token)(rr, req)

		if rr.Code == http.StatusOK {
			t.Error("Security breach: path traversal succeeded in replace handler")
		}
	})

	t.Run("Replace: missing file returns 404", func(t *testing.T) {
		body, _ := json.Marshal(map[string]string{
			"path":       "no_such_file.txt",
			"old_string": "x",
			"new_string": "y",
		})
		req := newAuthRequest("POST", "/replace", bytes.NewBuffer(body))
		rr := httptest.NewRecorder()
		handleReplace(rootDir, token)(rr, req)

		if rr.Code != http.StatusNotFound {
			t.Errorf("Expected 404 for missing file, got %d", rr.Code)
		}
	})

	// ── Append tests ──────────────────────────────────────────────────────────

	t.Run("Append: happy path appends content", func(t *testing.T) {
		filename := "append_me.txt"
		err := os.WriteFile(filepath.Join(tempDir, filename), []byte("line1\n"), 0644)
		if err != nil {
			t.Fatalf("Setup failed: %v", err)
		}

		body, _ := json.Marshal(map[string]string{
			"path":    filename,
			"content": "line2\n",
		})
		req := newAuthRequest("POST", "/append", bytes.NewBuffer(body))
		rr := httptest.NewRecorder()
		handleAppend(rootDir, token)(rr, req)

		if rr.Code != http.StatusOK {
			t.Fatalf("Append returned status %d: %s", rr.Code, rr.Body.String())
		}

		var resp map[string]interface{}
		json.Unmarshal(rr.Body.Bytes(), &resp)

		if resp["bytes_written"].(float64) != 6 {
			t.Errorf("Expected bytes_written=6, got %v", resp["bytes_written"])
		}

		// Verify disk content
		got, _ := os.ReadFile(filepath.Join(tempDir, filename))
		if string(got) != "line1\nline2\n" {
			t.Errorf("File content mismatch after append: %q", string(got))
		}
	})

	t.Run("Append: creates file if not exists", func(t *testing.T) {
		filename := "append_new.txt"

		body, _ := json.Marshal(map[string]string{
			"path":    filename,
			"content": "fresh content",
		})
		req := newAuthRequest("POST", "/append", bytes.NewBuffer(body))
		rr := httptest.NewRecorder()
		handleAppend(rootDir, token)(rr, req)

		if rr.Code != http.StatusOK {
			t.Fatalf("Append returned status %d: %s", rr.Code, rr.Body.String())
		}

		got, _ := os.ReadFile(filepath.Join(tempDir, filename))
		if string(got) != "fresh content" {
			t.Errorf("Expected 'fresh content', got %q", string(got))
		}
	})

	t.Run("Append: path traversal rejected", func(t *testing.T) {
		body, _ := json.Marshal(map[string]string{
			"path":    "../etc/evil.txt",
			"content": "malicious",
		})
		req := newAuthRequest("POST", "/append", bytes.NewBuffer(body))
		rr := httptest.NewRecorder()
		handleAppend(rootDir, token)(rr, req)

		if rr.Code == http.StatusOK {
			t.Error("Security breach: path traversal succeeded in append handler")
		}
	})

	// ── Mkdir tests ───────────────────────────────────────────────────────────

	t.Run("Mkdir: creates directory successfully", func(t *testing.T) {
		req := newAuthRequest("POST", "/mkdir?path=newdir", nil)
		rr := httptest.NewRecorder()
		handleMkdir(rootDir, token)(rr, req)

		if rr.Code != http.StatusCreated {
			t.Fatalf("Expected 201 Created, got %d: %s", rr.Code, rr.Body.String())
		}

		info, err := os.Stat(filepath.Join(tempDir, "newdir"))
		if err != nil {
			t.Fatalf("Directory does not exist on disk: %v", err)
		}
		if !info.IsDir() {
			t.Errorf("Expected a directory, got a file")
		}
	})

	t.Run("Mkdir: conflict when directory already exists", func(t *testing.T) {
		// Create directory first
		os.Mkdir(filepath.Join(tempDir, "existing_dir"), 0755)

		req := newAuthRequest("POST", "/mkdir?path=existing_dir", nil)
		rr := httptest.NewRecorder()
		handleMkdir(rootDir, token)(rr, req)

		if rr.Code != http.StatusConflict {
			t.Errorf("Expected 409 Conflict for duplicate directory, got %d", rr.Code)
		}
	})

	t.Run("Mkdir: missing path returns 400", func(t *testing.T) {
		req := newAuthRequest("POST", "/mkdir", nil)
		rr := httptest.NewRecorder()
		handleMkdir(rootDir, token)(rr, req)

		if rr.Code != http.StatusBadRequest {
			t.Errorf("Expected 400 Bad Request for missing path, got %d", rr.Code)
		}
	})

	t.Run("Mkdir: path traversal rejected", func(t *testing.T) {
		req := newAuthRequest("POST", "/mkdir?path=../escaped_dir", nil)
		rr := httptest.NewRecorder()
		handleMkdir(rootDir, token)(rr, req)

		if rr.Code == http.StatusCreated {
			t.Error("Security breach: path traversal succeeded in mkdir handler")
		}
	})

	t.Run("Mkdir: unauthorized request rejected", func(t *testing.T) {
		req := httptest.NewRequest("POST", "/mkdir?path=unauth_dir", nil)
		// No Authorization header
		rr := httptest.NewRecorder()
		handleMkdir(rootDir, token)(rr, req)

		if rr.Code != http.StatusUnauthorized {
			t.Errorf("Expected 401 Unauthorized, got %d", rr.Code)
		}
	})

	t.Run("Mkdir: created directory is visible in list", func(t *testing.T) {
		// Create a new directory via the handler
		req := newAuthRequest("POST", "/mkdir?path=listed_dir", nil)
		rr := httptest.NewRecorder()
		handleMkdir(rootDir, token)(rr, req)

		if rr.Code != http.StatusCreated {
			t.Fatalf("Mkdir failed: %d", rr.Code)
		}

		// Verify it appears in /list output
		req2 := newAuthRequest("GET", "/list", nil)
		rr2 := httptest.NewRecorder()
		handleList(rootDir, token)(rr2, req2)

		var resp map[string]interface{}
		json.Unmarshal(rr2.Body.Bytes(), &resp)

		files := resp["files"].([]interface{})
		found := false
		for _, f := range files {
			if f.(string) == "listed_dir/" {
				found = true
			}
		}
		if !found {
			t.Errorf("Newly created directory 'listed_dir/' not found in list output: %v", files)
		}
	})
}

func TestReadContentNotLogged(t *testing.T) {
	tempDir := t.TempDir()
	rootDir, err := os.OpenRoot(tempDir)
	if err != nil {
		t.Fatalf("Failed to open root: %v", err)
	}
	defer rootDir.Close()

	token := "secret-test-token"
	sentinel := "SENSITIVE_SECRET_MARKER_12345"

	filename := "secret.txt"
	if err := os.WriteFile(filepath.Join(tempDir, filename), []byte(sentinel), 0644); err != nil {
		t.Fatalf("Setup failed: %v", err)
	}

	// Capture log output
	var logBuf bytes.Buffer
	origOut := log.Writer()
	log.SetOutput(&logBuf)
	defer log.SetOutput(origOut)

	req := httptest.NewRequest("GET", "/read?path="+filename, nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rr := httptest.NewRecorder()
	handleRead(rootDir, token)(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("Read returned status %d", rr.Code)
	}

	// Response body must contain the sentinel (read works correctly)
	if !strings.Contains(rr.Body.String(), sentinel) {
		t.Errorf("Response body missing sentinel: got %q", rr.Body.String())
	}

	logOutput := logBuf.String()

	// Log must NOT contain the file content
	if strings.Contains(logOutput, sentinel) {
		t.Errorf("File content found in log output: %q", logOutput)
	}

	// Log must contain FILE_READ: and byte count
	if !strings.Contains(logOutput, "FILE_READ:") {
		t.Errorf("Expected FILE_READ: in log, got: %q", logOutput)
	}
	if !strings.Contains(logOutput, fmt.Sprintf("%d bytes", len(sentinel))) {
		t.Errorf("Expected byte count %d in log, got: %q", len(sentinel), logOutput)
	}
}
