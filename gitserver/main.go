package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/subtle"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// Submodule represents a single entry from .gitmodules.
type Submodule struct {
	Name string
	Path string
}

// gitState holds startup configuration and baseline commit data.
type gitState struct {
	gitDir             string
	workTree           string
	baselineCommit     string
	submoduleBaselines map[string]string
	submodules         []Submodule
}

// parseGitmodules parses .gitmodules in the given workTree and returns submodule entries.
func parseGitmodules(workTree string) []Submodule {
	f, err := os.Open(filepath.Join(workTree, ".gitmodules"))
	if err != nil {
		return nil
	}
	defer f.Close()

	var subs []Submodule
	var curName, curPath string

	flush := func() {
		if curName != "" && curPath != "" {
			subs = append(subs, Submodule{
				Name: curName,
				Path: filepath.Clean(curPath),
			})
		}
		curName = ""
		curPath = ""
	}

	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if strings.HasPrefix(line, `[submodule "`) && strings.HasSuffix(line, `"]`) {
			flush()
			curName = line[len(`[submodule "`): len(line)-2]
		} else if idx := strings.Index(line, "="); idx != -1 && curName != "" {
			key := strings.TrimSpace(line[:idx])
			val := strings.TrimSpace(line[idx+1:])
			if key == "path" {
				curPath = val
			}
		}
	}
	flush()
	return subs
}

// repoFor returns (gitDir, workTree) for a submodule path, or the root repo if empty.
func (s *gitState) repoFor(submodulePath string) (string, string) {
	if submodulePath != "" {
		clean := filepath.Clean(submodulePath)
		return filepath.Join(s.gitDir, "modules", clean),
			filepath.Join(s.workTree, clean)
	}
	return s.gitDir, s.workTree
}

// repoForFilePath auto-detects the owning repo for a file path by checking submodule prefixes.
func (s *gitState) repoForFilePath(filePath string) (string, string) {
	norm := filepath.Clean(filePath)
	for _, sub := range s.submodules {
		if norm == sub.Path || strings.HasPrefix(norm, sub.Path+string(filepath.Separator)) {
			return filepath.Join(s.gitDir, "modules", sub.Path),
				filepath.Join(s.workTree, sub.Path)
		}
	}
	return s.gitDir, s.workTree
}

// filterGitEnv strips GIT_DIR and GIT_WORK_TREE from the environment slice.
func filterGitEnv(env []string) []string {
	out := make([]string, 0, len(env))
	for _, e := range env {
		if strings.HasPrefix(e, "GIT_DIR=") || strings.HasPrefix(e, "GIT_WORK_TREE=") {
			continue
		}
		out = append(out, e)
	}
	return out
}

// runGit runs a git command with -c core.hooksPath=/dev/null and explicit GIT_DIR/GIT_WORK_TREE.
// Returns stdout, stderr, and exit code.
func runGit(gd, wt string, args ...string) (string, string, int) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	full := make([]string, 0, 2+len(args))
	full = append(full, "-c", "core.hooksPath=/dev/null")
	full = append(full, args...)

	cmd := exec.CommandContext(ctx, "git", full...)
	cmd.Env = append(filterGitEnv(os.Environ()),
		"GIT_DIR="+gd,
		"GIT_WORK_TREE="+wt,
	)

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	err := cmd.Run()
	exit := 0
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			exit = exitErr.ExitCode()
		} else {
			exit = 1
		}
	}
	return strings.TrimRight(stdout.String(), "\n"),
		strings.TrimRight(stderr.String(), "\n"),
		exit
}

// captureBaseline runs git rev-parse HEAD and returns the commit hash, or "" on failure.
func captureBaseline(gd, wt string) string {
	out, _, exit := runGit(gd, wt, "rev-parse", "HEAD")
	if exit != 0 {
		return ""
	}
	return strings.TrimSpace(out)
}

// writeJSON writes a JSON response with the given status code.
func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v) //nolint:errcheck
}

// verifyToken performs constant-time Bearer token verification.
func verifyToken(r *http.Request, expectedToken string) bool {
	authHeader := r.Header.Get("Authorization")
	if authHeader == "" {
		return false
	}
	parts := strings.SplitN(authHeader, " ", 2)
	if len(parts) != 2 || parts[0] != "Bearer" {
		return false
	}
	expectedBytes := []byte(expectedToken)
	providedBytes := []byte(parts[1])
	if len(expectedBytes) != len(providedBytes) {
		return false
	}
	return subtle.ConstantTimeCompare(providedBytes, expectedBytes) == 1
}

// handleHealth returns 200 OK with no authentication required.
func handleHealth() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}
}

// handleStatus runs git status --short.
// GET /status?submodule_path=...
func handleStatus(s *gitState, token string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !verifyToken(r, token) {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}
		submodulePath := r.URL.Query().Get("submodule_path")
		gd, wt := s.repoFor(submodulePath)
		stdout, stderr, exit := runGit(gd, wt, "status", "--short")
		log.Printf("GIT_STATUS: submodule=%q exit=%d", submodulePath, exit)
		if exit != 0 {
			http.Error(w, "git status failed: "+stderr, http.StatusInternalServerError)
			return
		}
		output := stdout
		if output == "" {
			output = "Working tree clean — no changes."
		}
		writeJSON(w, http.StatusOK, map[string]string{"output": output})
	}
}

// handleDiff runs git diff, optionally staged.
// GET /diff?staged=true&submodule_path=...
func handleDiff(s *gitState, token string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !verifyToken(r, token) {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}
		staged := r.URL.Query().Get("staged") == "true"
		submodulePath := r.URL.Query().Get("submodule_path")
		gd, wt := s.repoFor(submodulePath)

		args := []string{"diff"}
		if staged {
			args = append(args, "--cached")
		}
		stdout, stderr, exit := runGit(gd, wt, args...)
		log.Printf("GIT_DIFF: staged=%v submodule=%q exit=%d", staged, submodulePath, exit)
		if exit != 0 {
			http.Error(w, "git diff failed: "+stderr, http.StatusInternalServerError)
			return
		}
		output := stdout
		if output == "" {
			label := "unstaged"
			if staged {
				label = "staged"
			}
			output = "No " + label + " changes."
		}
		writeJSON(w, http.StatusOK, map[string]string{"output": output})
	}
}

// handleAdd stages files with multi-repo guard.
// POST /add  body: {"paths": [...]}
func handleAdd(s *gitState, token string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if !verifyToken(r, token) {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}
		var req struct {
			Paths []string `json:"paths"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid JSON", http.StatusBadRequest)
			return
		}
		if len(req.Paths) == 0 {
			http.Error(w, "paths is required", http.StatusBadRequest)
			return
		}

		// Multi-repo guard: all paths must resolve to the same repository.
		var commonGD, commonWT string
		for _, p := range req.Paths {
			gd, wt := s.repoForFilePath(p)
			if commonGD == "" {
				commonGD = gd
				commonWT = wt
			} else if commonGD != gd {
				http.Error(w, "paths span multiple repositories; stage each submodule separately", http.StatusBadRequest)
				return
			}
		}

		// When operating in a submodule, convert user paths (relative to root workspace)
		// to absolute paths so git resolves them correctly regardless of process CWD.
		rootWT := filepath.Clean(s.workTree)
		cleanWT := filepath.Clean(commonWT)
		var pathsToStage []string
		if cleanWT != rootWT {
			for _, p := range req.Paths {
				if p == "." {
					pathsToStage = append(pathsToStage, cleanWT)
				} else {
					pathsToStage = append(pathsToStage, filepath.Clean(filepath.Join(rootWT, p)))
				}
			}
		} else {
			pathsToStage = req.Paths
		}

		addArgs := append([]string{"add", "--"}, pathsToStage...)
		_, stderr, exit := runGit(commonGD, commonWT, addArgs...)
		log.Printf("GIT_ADD: paths=%v exit=%d", req.Paths, exit)
		if exit != 0 {
			http.Error(w, "git add failed: "+stderr, http.StatusInternalServerError)
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"output": "Staged: " + strings.Join(req.Paths, ", ")})
	}
}

// handleCommit creates a commit with --no-verify.
// POST /commit  body: {"message": "...", "submodule_path": "..."}
func handleCommit(s *gitState, token string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if !verifyToken(r, token) {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}
		var req struct {
			Message       string `json:"message"`
			SubmodulePath string `json:"submodule_path"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid JSON", http.StatusBadRequest)
			return
		}
		msg := strings.TrimSpace(req.Message)
		if msg == "" {
			http.Error(w, "message must not be empty", http.StatusBadRequest)
			return
		}
		gd, wt := s.repoFor(req.SubmodulePath)
		stdout, stderr, exit := runGit(gd, wt, "commit", "-m", msg, "--no-verify")
		log.Printf("GIT_COMMIT: submodule=%q exit=%d", req.SubmodulePath, exit)
		if exit != 0 {
			combined := stderr
			if stdout != "" {
				combined = stdout + "\n" + stderr
			}
			if strings.Contains(stdout, "nothing to commit") || strings.Contains(stderr, "nothing to commit") {
				writeJSON(w, http.StatusOK, map[string]string{"output": "Nothing to commit — working tree clean."})
				return
			}
			http.Error(w, "git commit failed: "+combined, http.StatusInternalServerError)
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"output": stdout})
	}
}

// handleLog runs git log --oneline with max_count clamped to 1–50.
// GET /log?max_count=N&submodule_path=...
func handleLog(s *gitState, token string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !verifyToken(r, token) {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}
		maxCount := 10
		if mc := r.URL.Query().Get("max_count"); mc != "" {
			if n, err := strconv.Atoi(mc); err == nil {
				maxCount = n
			}
		}
		if maxCount < 1 {
			maxCount = 1
		}
		if maxCount > 50 {
			maxCount = 50
		}
		submodulePath := r.URL.Query().Get("submodule_path")
		gd, wt := s.repoFor(submodulePath)
		stdout, stderr, exit := runGit(gd, wt, "log",
			fmt.Sprintf("--max-count=%d", maxCount),
			"--oneline",
			"--no-decorate",
		)
		log.Printf("GIT_LOG: max_count=%d submodule=%q exit=%d", maxCount, submodulePath, exit)
		if exit != 0 {
			if strings.Contains(stderr, "does not have any commits") {
				writeJSON(w, http.StatusOK, map[string]string{"output": "No commits yet."})
				return
			}
			http.Error(w, "git log failed: "+stderr, http.StatusInternalServerError)
			return
		}
		output := stdout
		if output == "" {
			output = "No commits yet."
		}
		writeJSON(w, http.StatusOK, map[string]string{"output": output})
	}
}

// handleReset runs git reset --soft HEAD~N with baseline floor enforcement.
// POST /reset  body: {"count": N, "submodule_path": "..."}
func handleReset(s *gitState, token string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if !verifyToken(r, token) {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}
		var req struct {
			Count         int    `json:"count"`
			SubmodulePath string `json:"submodule_path"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid JSON", http.StatusBadRequest)
			return
		}
		if req.Count <= 0 {
			req.Count = 1
		}
		if req.Count > 5 {
			req.Count = 5
		}

		gd, wt := s.repoFor(req.SubmodulePath)

		// Select baseline for the target repository.
		var baseline string
		if req.SubmodulePath != "" {
			baseline = s.submoduleBaselines[filepath.Clean(req.SubmodulePath)]
		} else {
			baseline = s.baselineCommit
		}
		if baseline == "" {
			http.Error(w, "Cannot reset — no baseline commit (empty repo at startup)", http.StatusBadRequest)
			return
		}

		// Resolve the target commit.
		target, _, exitTarget := runGit(gd, wt, "rev-parse", fmt.Sprintf("HEAD~%d", req.Count))
		if exitTarget != 0 {
			http.Error(w, fmt.Sprintf("Cannot reset %d commits — not enough history", req.Count), http.StatusBadRequest)
			return
		}
		target = strings.TrimSpace(target)

		// Enforce baseline floor: allow reset TO baseline but not past it.
		if target != baseline {
			_, _, exitAnc := runGit(gd, wt, "merge-base", "--is-ancestor", target, baseline)
			if exitAnc == 0 {
				baselineShort := baseline
				if len(baselineShort) > 12 {
					baselineShort = baselineShort[:12]
				}
				http.Error(w, fmt.Sprintf(
					"Cannot reset %d commits — would go past the baseline commit (%s). "+
						"You can only undo commits created during this session.",
					req.Count, baselineShort,
				), http.StatusBadRequest)
				return
			}
		}

		_, stderr, exit := runGit(gd, wt, "reset", "--soft", fmt.Sprintf("HEAD~%d", req.Count))
		log.Printf("GIT_RESET: count=%d submodule=%q exit=%d", req.Count, req.SubmodulePath, exit)
		if exit != 0 {
			http.Error(w, "git reset failed: "+stderr, http.StatusInternalServerError)
			return
		}
		targetShort := target
		if len(targetShort) > 12 {
			targetShort = targetShort[:12]
		}
		writeJSON(w, http.StatusOK, map[string]string{
			"output": fmt.Sprintf("Reset %d commit(s). Changes are still staged. HEAD is now at %s.", req.Count, targetShort),
		})
	}
}

// setupRouter wires all routes for testability.
func setupRouter(s *gitState, token string) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", handleHealth())
	mux.HandleFunc("/status", handleStatus(s, token))
	mux.HandleFunc("/diff", handleDiff(s, token))
	mux.HandleFunc("/add", handleAdd(s, token))
	mux.HandleFunc("/commit", handleCommit(s, token))
	mux.HandleFunc("/log", handleLog(s, token))
	mux.HandleFunc("/reset", handleReset(s, token))
	return mux
}

func main() {
	token := os.Getenv("GIT_API_TOKEN")
	if token == "" {
		log.Fatal("GIT_API_TOKEN is required")
	}

	gd := os.Getenv("GIT_DIR")
	if gd == "" {
		gd = "/gitdir"
	}
	wt := os.Getenv("GIT_WORK_TREE")
	if wt == "" {
		wt = "/workspace"
	}

	subs := parseGitmodules(wt)

	// Load or capture the root baseline commit.
	baseline := os.Getenv("GIT_BASELINE_COMMIT")
	if baseline == "" {
		baseline = captureBaseline(gd, wt)
		if baseline != "" {
			log.Printf("Baseline commit (captured): %s", baseline)
		} else {
			log.Println("No baseline commit (empty repo)")
		}
	} else {
		log.Printf("Baseline commit (from env): %s", baseline)
	}

	// Load per-submodule baselines.
	subBaselines := make(map[string]string)
	for _, sub := range subs {
		sgd := filepath.Join(gd, "modules", sub.Path)
		swt := filepath.Join(wt, sub.Path)
		bc := captureBaseline(sgd, swt)
		if bc != "" {
			subBaselines[sub.Path] = bc
			log.Printf("Submodule baseline (%s): %s", sub.Path, bc)
		} else {
			log.Printf("Submodule %s has no commits yet — skipping baseline.", sub.Path)
		}
	}

	state := &gitState{
		gitDir:             gd,
		workTree:           wt,
		baselineCommit:     baseline,
		submoduleBaselines: subBaselines,
		submodules:         subs,
	}

	mux := setupRouter(state, token)

	server := &http.Server{
		Addr:    ":8443",
		Handler: mux,
		TLSConfig: &tls.Config{
			MinVersion: tls.VersionTLS13,
		},
	}

	log.Println("Git server listening on :8443 with TLS")
	log.Fatal(server.ListenAndServeTLS("/app/certs/git.crt", "/app/certs/git.key"))
}
