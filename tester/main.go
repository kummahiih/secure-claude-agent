package main

import (
	"crypto/subtle"
	"crypto/tls"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"sync"
	"time"
)

// testResult holds the outcome of the most recent test run.
type testResult struct {
	Status    string `json:"status"`    // "pass", "fail", or "pending"
	ExitCode  int    `json:"exit_code"`
	Timestamp string `json:"timestamp"`
	Output    string `json:"output"`
}

var (
	mu     sync.Mutex
	result = testResult{Status: "pending"}
)

// handleRun executes the tester Docker container and records the result.
// POST /run — returns {"status":"started"} immediately; run is async.
func handleRun(token string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !verifyToken(r, token) {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}

		workspaceHostPath := os.Getenv("WORKSPACE_HOST_PATH")
		testerImage := os.Getenv("TESTER_IMAGE")
		if testerImage == "" {
			testerImage = "test-runner"
		}

		// Respond immediately; run test asynchronously.
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]string{"status": "started"})

		go func() {
			args := []string{"run", "--rm"}
			if workspaceHostPath != "" {
				args = append(args, "-v", workspaceHostPath+":/project:ro")
			}
			args = append(args, testerImage)

			cmd := exec.Command("docker", args...)
			out, err := cmd.CombinedOutput()

			exitCode := 0
			status := "pass"
			if err != nil {
				if exitErr, ok := err.(*exec.ExitError); ok {
					exitCode = exitErr.ExitCode()
				} else {
					exitCode = 1
				}
				status = "fail"
			}

			mu.Lock()
			result = testResult{
				Status:    status,
				ExitCode:  exitCode,
				Timestamp: time.Now().UTC().Format(time.RFC3339),
				Output:    string(out),
			}
			mu.Unlock()

			log.Printf("RUN_COMPLETE: status=%s exit_code=%d", status, exitCode)
		}()
	}
}

// handleResults returns the stored test result as JSON.
// GET /results
func handleResults(token string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !verifyToken(r, token) {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}

		mu.Lock()
		res := result
		mu.Unlock()

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(res)
	}
}

// handleHealth returns 200 OK with no authentication required.
func handleHealth() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}
}

// setupRouter isolates the routing logic so it can be tested independently.
func setupRouter(token string) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("/run", handleRun(token))
	mux.HandleFunc("/results", handleResults(token))
	mux.HandleFunc("/health", handleHealth())
	return mux
}

// verifyToken checks the Bearer token in the Authorization header.
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

	// ConstantTimeCompare requires equal lengths.
	if len(expectedBytes) != len(providedBytes) {
		return false
	}

	return subtle.ConstantTimeCompare(providedBytes, expectedBytes) == 1
}

func main() {
	token := os.Getenv("MCP_API_TOKEN")
	if token == "" {
		log.Fatal("MCP_API_TOKEN is required")
	}

	mux := setupRouter(token)

	server := &http.Server{
		Addr:    ":8443",
		Handler: mux,
		TLSConfig: &tls.Config{
			MinVersion: tls.VersionTLS12,
		},
	}

	log.Println("Tester server listening on :8443 with TLS")
	log.Fatal(server.ListenAndServeTLS("/app/certs/tester.crt", "/app/certs/tester.key"))
}
