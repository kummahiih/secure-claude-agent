package main

import (
	"bytes"
	"crypto/tls"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

const testToken = "test-token"

// gitSetup initialises a bare git repo in a temp dir and returns a gitState.
// Two commits are created so baseline-floor tests have room to operate.
func gitSetup(t *testing.T) (*gitState, string) {
	t.Helper()

	// Suppress system/global git config interference.
	t.Setenv("GIT_CONFIG_NOSYSTEM", "1")
	t.Setenv("GIT_AUTHOR_NAME", "Test")
	t.Setenv("GIT_AUTHOR_EMAIL", "test@test.com")
	t.Setenv("GIT_COMMITTER_NAME", "Test")
	t.Setenv("GIT_COMMITTER_EMAIL", "test@test.com")

	dir := t.TempDir()
	gd := filepath.Join(dir, ".git")
	wt := dir

	run := func(args ...string) string {
		t.Helper()
		cmd := exec.Command("git", args...)
		cmd.Env = append(filterGitEnv(os.Environ()),
			"GIT_CONFIG_NOSYSTEM=1",
			"GIT_AUTHOR_NAME=Test",
			"GIT_AUTHOR_EMAIL=test@test.com",
			"GIT_COMMITTER_NAME=Test",
			"GIT_COMMITTER_EMAIL=test@test.com",
			"GIT_DIR="+gd,
			"GIT_WORK_TREE="+wt,
		)
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %s", args, out)
		}
		return strings.TrimSpace(string(out))
	}

	run("init")
	run("config", "user.email", "test@test.com")
	run("config", "user.name", "Test")

	// Pre-baseline commit (so baseline enforcement has a commit to protect).
	os.WriteFile(filepath.Join(dir, "pre.txt"), []byte("pre"), 0644)
	run("add", "pre.txt")
	run("commit", "-m", "pre-baseline", "--no-verify")

	// Baseline commit.
	os.WriteFile(filepath.Join(dir, "base.txt"), []byte("base"), 0644)
	run("add", "base.txt")
	run("commit", "-m", "baseline commit", "--no-verify")
	baseline := run("rev-parse", "HEAD")

	state := &gitState{
		gitDir:             gd,
		workTree:           wt,
		baselineCommit:     baseline,
		submoduleBaselines: map[string]string{},
		submodules:         nil,
	}
	return state, dir
}

// doGet issues an authenticated GET and returns the response.
func doGet(t *testing.T, url string) *http.Response {
	t.Helper()
	req, _ := http.NewRequest(http.MethodGet, url, nil)
	req.Header.Set("Authorization", "Bearer "+testToken)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	return resp
}

// doPost issues an authenticated POST with a JSON body.
func doPost(t *testing.T, url string, body interface{}) *http.Response {
	t.Helper()
	b, _ := json.Marshal(body)
	req, _ := http.NewRequest(http.MethodPost, url, bytes.NewReader(b))
	req.Header.Set("Authorization", "Bearer "+testToken)
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	return resp
}

func decodeOutput(t *testing.T, resp *http.Response) string {
	t.Helper()
	defer resp.Body.Close()
	var m map[string]string
	if err := json.NewDecoder(resp.Body).Decode(&m); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	return m["output"]
}

// --- Unit tests ---

func TestParseGitmodules(t *testing.T) {
	dir := t.TempDir()
	content := `[submodule "cluster/agent"]
	path = cluster/agent
	url = ../agent

[submodule "cluster/tester"]
	path = cluster/tester
	url = ../tester
`
	os.WriteFile(filepath.Join(dir, ".gitmodules"), []byte(content), 0644)
	subs := parseGitmodules(dir)
	if len(subs) != 2 {
		t.Fatalf("expected 2 submodules, got %d", len(subs))
	}
	if subs[0].Name != "cluster/agent" || subs[0].Path != "cluster/agent" {
		t.Errorf("unexpected submodule[0]: %+v", subs[0])
	}
	if subs[1].Name != "cluster/tester" || subs[1].Path != "cluster/tester" {
		t.Errorf("unexpected submodule[1]: %+v", subs[1])
	}
}

func TestParseGitmodulesAbsent(t *testing.T) {
	subs := parseGitmodules(t.TempDir())
	if subs != nil {
		t.Fatalf("expected nil, got %v", subs)
	}
}

func TestVerifyToken(t *testing.T) {
	tests := []struct {
		header string
		want   bool
	}{
		{"Bearer test-token", true},
		{"Bearer wrong-token", false},
		{"", false},
		{"Basic test-token", false},
		{"Bearer ", false},
	}
	for _, tc := range tests {
		req, _ := http.NewRequest(http.MethodGet, "/", nil)
		if tc.header != "" {
			req.Header.Set("Authorization", tc.header)
		}
		if got := verifyToken(req, "test-token"); got != tc.want {
			t.Errorf("header=%q: got %v, want %v", tc.header, got, tc.want)
		}
	}
}

// --- Handler tests ---

func TestHealth(t *testing.T) {
	state, _ := gitSetup(t)
	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/health")
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
}

func TestHealthNoAuth(t *testing.T) {
	state, _ := gitSetup(t)
	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	// /health must work without a token.
	resp, err := http.Get(srv.URL + "/health")
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
}

func TestStatusClean(t *testing.T) {
	state, _ := gitSetup(t)
	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	resp := doGet(t, srv.URL+"/status")
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
	out := decodeOutput(t, resp)
	if !strings.Contains(out, "clean") {
		t.Errorf("expected clean status, got: %q", out)
	}
}

func TestStatusDirty(t *testing.T) {
	state, dir := gitSetup(t)
	os.WriteFile(filepath.Join(dir, "dirty.txt"), []byte("dirty"), 0644)

	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	resp := doGet(t, srv.URL+"/status")
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
	out := decodeOutput(t, resp)
	if !strings.Contains(out, "dirty.txt") {
		t.Errorf("expected dirty.txt in status, got: %q", out)
	}
}

func TestDiffUnstaged(t *testing.T) {
	state, dir := gitSetup(t)
	// Modify a tracked file without staging.
	os.WriteFile(filepath.Join(dir, "base.txt"), []byte("modified"), 0644)

	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	resp := doGet(t, srv.URL+"/diff")
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
	out := decodeOutput(t, resp)
	if !strings.Contains(out, "modified") {
		t.Errorf("expected diff output, got: %q", out)
	}
}

func TestDiffStaged(t *testing.T) {
	state, dir := gitSetup(t)
	os.WriteFile(filepath.Join(dir, "staged.txt"), []byte("staged content"), 0644)
	runGit(state.gitDir, state.workTree, "add", "staged.txt")

	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	resp := doGet(t, srv.URL+"/diff?staged=true")
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
	out := decodeOutput(t, resp)
	if !strings.Contains(out, "staged.txt") {
		t.Errorf("expected staged diff, got: %q", out)
	}
}

func TestDiffNone(t *testing.T) {
	state, _ := gitSetup(t)
	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	resp := doGet(t, srv.URL+"/diff")
	out := decodeOutput(t, resp)
	if !strings.Contains(out, "No unstaged changes") {
		t.Errorf("expected no-changes message, got: %q", out)
	}
}

func TestAdd(t *testing.T) {
	state, dir := gitSetup(t)
	os.WriteFile(filepath.Join(dir, "new.txt"), []byte("new"), 0644)

	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	resp := doPost(t, srv.URL+"/add", map[string]interface{}{"paths": []string{"new.txt"}})
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
	out := decodeOutput(t, resp)
	if !strings.Contains(out, "new.txt") {
		t.Errorf("expected staged confirmation, got: %q", out)
	}
}

func TestAddNoPaths(t *testing.T) {
	state, _ := gitSetup(t)
	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	resp := doPost(t, srv.URL+"/add", map[string]interface{}{"paths": []string{}})
	resp.Body.Close()
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", resp.StatusCode)
	}
}

func TestAddMultiRepoGuard(t *testing.T) {
	// Use a fake state with two submodule entries — no real git needed for this check.
	state := &gitState{
		gitDir:   "/fake/gitdir",
		workTree: "/fake/workspace",
		submodules: []Submodule{
			{Name: "sub1", Path: "sub1"},
			{Name: "sub2", Path: "sub2"},
		},
		submoduleBaselines: map[string]string{},
	}
	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	resp := doPost(t, srv.URL+"/add", map[string]interface{}{
		"paths": []string{"sub1/foo.go", "sub2/bar.go"},
	})
	resp.Body.Close()
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("expected 400 for cross-repo paths, got %d", resp.StatusCode)
	}
}

func TestCommit(t *testing.T) {
	state, dir := gitSetup(t)
	os.WriteFile(filepath.Join(dir, "c.txt"), []byte("c"), 0644)
	runGit(state.gitDir, state.workTree, "add", "c.txt")

	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	resp := doPost(t, srv.URL+"/commit", map[string]interface{}{"message": "test commit"})
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
	out := decodeOutput(t, resp)
	if out == "" {
		t.Error("expected non-empty commit output")
	}
}

func TestCommitEmptyMessage(t *testing.T) {
	state, _ := gitSetup(t)
	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	resp := doPost(t, srv.URL+"/commit", map[string]interface{}{"message": "  "})
	resp.Body.Close()
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", resp.StatusCode)
	}
}

func TestCommitNothingToCommit(t *testing.T) {
	state, _ := gitSetup(t)
	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	resp := doPost(t, srv.URL+"/commit", map[string]interface{}{"message": "empty"})
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
	out := decodeOutput(t, resp)
	if !strings.Contains(out, "Nothing to commit") {
		t.Errorf("expected nothing-to-commit message, got: %q", out)
	}
}

func TestLog(t *testing.T) {
	state, _ := gitSetup(t)
	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	resp := doGet(t, srv.URL+"/log")
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
	out := decodeOutput(t, resp)
	if !strings.Contains(out, "baseline commit") {
		t.Errorf("expected commit message in log, got: %q", out)
	}
}

func TestLogMaxCount(t *testing.T) {
	state, _ := gitSetup(t)
	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	// max_count=1 should return exactly 1 line.
	resp := doGet(t, srv.URL+"/log?max_count=1")
	out := decodeOutput(t, resp)
	lines := strings.Split(strings.TrimSpace(out), "\n")
	if len(lines) != 1 {
		t.Errorf("expected 1 log line, got %d: %q", len(lines), out)
	}
}

func TestLogMaxCountClamped(t *testing.T) {
	state, _ := gitSetup(t)
	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	// max_count=999 should be clamped to 50 (no error, just limited output).
	resp := doGet(t, srv.URL+"/log?max_count=999")
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
	resp.Body.Close()
}

func TestResetSoft(t *testing.T) {
	state, dir := gitSetup(t)

	// Add an agent commit on top of the baseline.
	os.WriteFile(filepath.Join(dir, "agent.txt"), []byte("agent"), 0644)
	runGit(state.gitDir, state.workTree, "add", "agent.txt")
	runGit(state.gitDir, state.workTree, "commit", "-m", "agent commit", "--no-verify")

	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	resp := doPost(t, srv.URL+"/reset", map[string]interface{}{"count": 1})
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
	out := decodeOutput(t, resp)
	if !strings.Contains(out, "Reset 1 commit") {
		t.Errorf("expected reset confirmation, got: %q", out)
	}
}

func TestResetSoftDefaultCount(t *testing.T) {
	state, dir := gitSetup(t)

	os.WriteFile(filepath.Join(dir, "a2.txt"), []byte("a2"), 0644)
	runGit(state.gitDir, state.workTree, "add", "a2.txt")
	runGit(state.gitDir, state.workTree, "commit", "-m", "agent2", "--no-verify")

	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	// count=0 should be treated as 1.
	resp := doPost(t, srv.URL+"/reset", map[string]interface{}{"count": 0})
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
	out := decodeOutput(t, resp)
	if !strings.Contains(out, "Reset 1 commit") {
		t.Errorf("expected reset 1, got: %q", out)
	}
}

func TestResetSoftBlockedByBaseline(t *testing.T) {
	state, dir := gitSetup(t)

	// Add one agent commit.
	os.WriteFile(filepath.Join(dir, "agent.txt"), []byte("agent"), 0644)
	runGit(state.gitDir, state.workTree, "add", "agent.txt")
	runGit(state.gitDir, state.workTree, "commit", "-m", "agent commit", "--no-verify")

	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	// HEAD~2 from current HEAD lands on the pre-baseline commit — must be blocked.
	resp := doPost(t, srv.URL+"/reset", map[string]interface{}{"count": 2})
	resp.Body.Close()
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("expected 400 (baseline blocked), got %d", resp.StatusCode)
	}
}

func TestResetSoftNoBaseline(t *testing.T) {
	state, dir := gitSetup(t)
	state.baselineCommit = "" // simulate empty-repo startup

	os.WriteFile(filepath.Join(dir, "x.txt"), []byte("x"), 0644)
	runGit(state.gitDir, state.workTree, "add", "x.txt")
	runGit(state.gitDir, state.workTree, "commit", "-m", "c", "--no-verify")

	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	resp := doPost(t, srv.URL+"/reset", map[string]interface{}{"count": 1})
	resp.Body.Close()
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("expected 400 (no baseline), got %d", resp.StatusCode)
	}
}

// --- Auth tests ---

func TestUnauthorizedMissingToken(t *testing.T) {
	state, _ := gitSetup(t)
	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	endpoints := []struct {
		method string
		path   string
	}{
		{http.MethodGet, "/status"},
		{http.MethodGet, "/diff"},
		{http.MethodPost, "/add"},
		{http.MethodPost, "/commit"},
		{http.MethodGet, "/log"},
		{http.MethodPost, "/reset"},
	}
	for _, ep := range endpoints {
		req, _ := http.NewRequest(ep.method, srv.URL+ep.path, bytes.NewReader([]byte("{}")))
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatalf("%s %s: %v", ep.method, ep.path, err)
		}
		resp.Body.Close()
		if resp.StatusCode != http.StatusUnauthorized {
			t.Errorf("%s %s: expected 401, got %d", ep.method, ep.path, resp.StatusCode)
		}
	}
}

func TestUnauthorizedWrongToken(t *testing.T) {
	state, _ := gitSetup(t)
	srv := httptest.NewServer(setupRouter(state, testToken))
	defer srv.Close()

	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/status", nil)
	req.Header.Set("Authorization", "Bearer wrong-token")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", resp.StatusCode)
	}
}

// --- TLS test ---

func TestTLSMinVersion13(t *testing.T) {
	state := &gitState{
		gitDir:             "/dev/null",
		workTree:           "/dev/null",
		submoduleBaselines: map[string]string{},
	}
	ts := httptest.NewUnstartedServer(setupRouter(state, testToken))
	ts.TLS = &tls.Config{MinVersion: tls.VersionTLS13}
	ts.StartTLS()
	defer ts.Close()

	// TLS 1.3 client — must succeed.
	resp, err := ts.Client().Get(ts.URL + "/health")
	if err != nil {
		t.Fatalf("TLS 1.3 client failed: %v", err)
	}
	resp.Body.Close()

	// TLS 1.2 max client — must be rejected.
	base := ts.Client().Transport.(*http.Transport).Clone()
	base.TLSClientConfig.MaxVersion = tls.VersionTLS12
	_, err = (&http.Client{Transport: base}).Get(ts.URL + "/health")
	if err == nil {
		t.Error("expected TLS 1.2 client to be rejected")
	}
}
