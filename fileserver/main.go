package main

import (
	"bufio"
	"crypto/sha256"
	"crypto/subtle"
	"crypto/tls"
	"encoding/json"
	"io"
	"io/fs"
	"log"
	"net/http"
	"os"
	"regexp"
	"strings"
)

func handleRead(rootDir *os.Root, token string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !verifyToken(r, token) {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}

		targetPath := r.URL.Query().Get("path")

		// Reject missing or empty file_path parameter.
		if targetPath == "" {
			http.Error(w, "Bad Request: file_path is required", http.StatusBadRequest)
			return
		}

		// Reject paths containing null bytes.
		if strings.Contains(targetPath, "\x00") {
			http.Error(w, "Bad Request: file_path must not contain null bytes", http.StatusBadRequest)
			return
		}

		// Reject paths exceeding 4096 bytes.
		if len(targetPath) > 4096 {
			http.Error(w, "Bad Request: file_path must not exceed 4096 bytes", http.StatusBadRequest)
			return
		}

		log.Printf("Received request for %s", targetPath)

		file, err := rootDir.Open(targetPath)
		if err != nil {
			http.Error(w, "Access denied or file not found", http.StatusNotFound)
			return
		}
		defer file.Close()

		// 2. Read the content into a byte slice
		// Using io.ReadAll is fine for typical workspace files
		data, err := io.ReadAll(file)
		if err != nil {
			log.Printf("Read error: %v", err)
			http.Error(w, "Error reading file", http.StatusInternalServerError)
			return
		}

		// 1. Log the content for your own sanity
		log.Printf("FILE_READ: %s (%d bytes, sha256=%x)", targetPath, len(data), sha256.Sum256(data))

		// 2. Set as plain text so the LLM sees it as a direct message
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")

		// 3. SET STATUS CODE SECOND
		w.WriteHeader(http.StatusOK)

		// 3. Write the raw bytes directly to the response
		w.Write(data)
	}
}

func handleRemove(rootDir *os.Root, token string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !verifyToken(r, token) {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}
		targetPath := r.URL.Query().Get("path")

		// rootDir.Remove is the secure way to delete within the jail
		err := rootDir.Remove(targetPath)
		if err != nil {
			log.Printf("DELETE_ERROR: %v", err)
			http.Error(w, "Failed to delete file", http.StatusInternalServerError)
			return
		}
		w.WriteHeader(http.StatusOK)
		log.Printf("FILE_REMOVED: %s", targetPath)
	}
}

func handleCreate(rootDir *os.Root, token string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !verifyToken(r, token) {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}
		targetPath := r.URL.Query().Get("path")

		// O_CREATE | O_EXCL prevents overwriting existing files
		f, err := rootDir.OpenFile(targetPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
		if err != nil {
			http.Error(w, "File already exists or invalid path", http.StatusBadRequest)
			return
		}
		f.Close()
		w.WriteHeader(http.StatusCreated)
		log.Printf("FILE_CREATED: %s", targetPath)
	}
}

func handleWrite(rootDir *os.Root, token string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !verifyToken(r, token) {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}

		// Define the expected JSON payload
		var req struct {
			Path    string `json:"path"`
			Content string `json:"content"`
		}

		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid JSON payload", http.StatusBadRequest)
			return
		}

		// Open file with Truncate to replace whole content
		// 0644 gives read/write to owner and read-only to group/others
		f, err := rootDir.OpenFile(req.Path, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0644)
		if err != nil {
			log.Printf("WRITE_ERROR: %v", err)
			http.Error(w, "Could not open file for writing", http.StatusInternalServerError)
			return
		}
		defer f.Close()

		_, err = f.WriteString(req.Content)
		if err != nil {
			log.Printf("WRITE_ERROR: %v", err)
			http.Error(w, "Failed to write content", http.StatusInternalServerError)
			return
		}

		w.WriteHeader(http.StatusOK)
		log.Printf("FILE_WRITTEN: %s (%d bytes)", req.Path, len(req.Content))
	}
}

func handleList(rootDir *os.Root, token string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !verifyToken(r, token) {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}

		var files []string
		// Use .FS() to satisfy the fs.FS interface for WalkDir
		err := fs.WalkDir(rootDir.FS(), ".", func(path string, d fs.DirEntry, err error) error {
			if err != nil {
				return nil // Skip paths that can't be accessed
			}
			if path == "." {
				return nil
			}

			entry := path
			if d.IsDir() {
				entry += "/"
			}
			files = append(files, entry)
			return nil
		})

		if err != nil {
			http.Error(w, "Internal Server Error", http.StatusInternalServerError)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"files": files,
			"count": len(files),
		})
	}
}

// handleGrep searches all files in the workspace for lines matching a regexp pattern.
// POST /grep  body: {"pattern":"<regexp>", "max_results": 100}
// Returns: [{"file":"...","line_number":N,"line":"..."}]
func handleGrep(rootDir *os.Root, token string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !verifyToken(r, token) {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}

		var req struct {
			Pattern    string `json:"pattern"`
			MaxResults int    `json:"max_results"`
		}
		req.MaxResults = 100 // default before decode

		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid JSON payload", http.StatusBadRequest)
			return
		}

		if req.Pattern == "" {
			http.Error(w, "Bad Request: pattern is required", http.StatusBadRequest)
			return
		}

		if req.MaxResults <= 0 {
			req.MaxResults = 100
		}

		re, err := regexp.Compile(req.Pattern)
		if err != nil {
			http.Error(w, "Bad Request: invalid pattern", http.StatusBadRequest)
			return
		}

		type Match struct {
			File       string `json:"file"`
			LineNumber int    `json:"line_number"`
			Line       string `json:"line"`
		}

		matches := []Match{}

		fs.WalkDir(rootDir.FS(), ".", func(path string, d fs.DirEntry, err error) error {
			if err != nil || d.IsDir() {
				return nil
			}
			if len(matches) >= req.MaxResults {
				return nil
			}

			f, err := rootDir.Open(path)
			if err != nil {
				return nil
			}
			defer f.Close()

			scanner := bufio.NewScanner(f)
			lineNum := 0
			for scanner.Scan() {
				lineNum++
				line := scanner.Text()
				if re.MatchString(line) {
					matches = append(matches, Match{
						File:       path,
						LineNumber: lineNum,
						Line:       line,
					})
					if len(matches) >= req.MaxResults {
						break
					}
				}
			}
			return nil
		})

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(matches)
	}
}

// handleReplace replaces all occurrences of old_string with new_string in the given file.
// POST /replace  body: {"path":"...","old_string":"...","new_string":"..."}
// Returns: {"replacements_made": N}  — fails 422 if N == 0.
func handleReplace(rootDir *os.Root, token string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !verifyToken(r, token) {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}

		var req struct {
			Path      string `json:"path"`
			OldString string `json:"old_string"`
			NewString string `json:"new_string"`
		}

		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid JSON payload", http.StatusBadRequest)
			return
		}

		if req.Path == "" {
			http.Error(w, "Bad Request: path is required", http.StatusBadRequest)
			return
		}

		f, err := rootDir.Open(req.Path)
		if err != nil {
			http.Error(w, "File not found", http.StatusNotFound)
			return
		}
		data, err := io.ReadAll(f)
		f.Close()
		if err != nil {
			http.Error(w, "Error reading file", http.StatusInternalServerError)
			return
		}

		original := string(data)
		replacements := strings.Count(original, req.OldString)

		if replacements == 0 {
			http.Error(w, "Unprocessable Entity: old_string not found in file", http.StatusUnprocessableEntity)
			return
		}

		updated := strings.ReplaceAll(original, req.OldString, req.NewString)

		wf, err := rootDir.OpenFile(req.Path, os.O_WRONLY|os.O_TRUNC, 0644)
		if err != nil {
			http.Error(w, "Error opening file for writing", http.StatusInternalServerError)
			return
		}
		defer wf.Close()

		if _, err = wf.WriteString(updated); err != nil {
			http.Error(w, "Error writing file", http.StatusInternalServerError)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]int{"replacements_made": replacements})
	}
}

// handleMkdir creates a new directory inside the workspace jail.
// POST /mkdir?path=<dir_path>
// Returns 201 Created on success, 409 Conflict if it already exists.
func handleMkdir(rootDir *os.Root, token string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !verifyToken(r, token) {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}

		targetPath := r.URL.Query().Get("path")
		if targetPath == "" {
			http.Error(w, "Bad Request: path is required", http.StatusBadRequest)
			return
		}

		err := rootDir.Mkdir(targetPath, 0755)
		if err != nil {
			if os.IsExist(err) {
				http.Error(w, "Directory already exists", http.StatusConflict)
				return
			}
			log.Printf("MKDIR_ERROR: %v", err)
			http.Error(w, "Failed to create directory", http.StatusBadRequest)
			return
		}

		w.WriteHeader(http.StatusCreated)
		log.Printf("DIR_CREATED: %s", targetPath)
	}
}

// handleAppend appends content to an existing (or new) file.
// POST /append  body: {"path":"...","content":"..."}
// Returns: {"bytes_written": N}
func handleAppend(rootDir *os.Root, token string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !verifyToken(r, token) {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}

		var req struct {
			Path    string `json:"path"`
			Content string `json:"content"`
		}

		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid JSON payload", http.StatusBadRequest)
			return
		}

		if req.Path == "" {
			http.Error(w, "Bad Request: path is required", http.StatusBadRequest)
			return
		}

		f, err := rootDir.OpenFile(req.Path, os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0644)
		if err != nil {
			log.Printf("APPEND_ERROR: %v", err)
			http.Error(w, "Could not open file for appending", http.StatusInternalServerError)
			return
		}
		defer f.Close()

		n, err := f.WriteString(req.Content)
		if err != nil {
			http.Error(w, "Error appending to file", http.StatusInternalServerError)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]int{"bytes_written": n})
		log.Printf("FILE_APPENDED: %s (%d bytes)", req.Path, n)
	}
}

// handleCopy copies a file from src to dst within the workspace jail.
// POST /copy  body: {"src":"...","dst":"...","overwrite":false}
// Returns 200 OK, 400 Bad Request, 404 Not Found, 409 Conflict, 500 Internal Server Error.
func handleCopy(rootDir *os.Root, token string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !verifyToken(r, token) {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}

		var req struct {
			Src       string `json:"src"`
			Dst       string `json:"dst"`
			Overwrite bool   `json:"overwrite"`
		}

		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid JSON payload", http.StatusBadRequest)
			return
		}

		if req.Src == "" || req.Dst == "" {
			http.Error(w, "Bad Request: src and dst are required", http.StatusBadRequest)
			return
		}

		// Read source file via os.Root (path traversal structurally impossible)
		srcFile, err := rootDir.Open(req.Src)
		if err != nil {
			http.Error(w, "Source file not found", http.StatusNotFound)
			return
		}
		data, err := io.ReadAll(srcFile)
		srcFile.Close()
		if err != nil {
			log.Printf("COPY_READ_ERROR: %v", err)
			http.Error(w, "Error reading source file", http.StatusInternalServerError)
			return
		}

		// Open destination with appropriate flags
		flags := os.O_WRONLY | os.O_CREATE | os.O_EXCL
		if req.Overwrite {
			flags = os.O_WRONLY | os.O_CREATE | os.O_TRUNC
		}

		dstFile, err := rootDir.OpenFile(req.Dst, flags, 0644)
		if err != nil {
			if os.IsExist(err) {
				http.Error(w, "Destination already exists", http.StatusConflict)
				return
			}
			log.Printf("COPY_OPEN_DST_ERROR: %v", err)
			http.Error(w, "Error opening destination file", http.StatusInternalServerError)
			return
		}
		defer dstFile.Close()

		if _, err = dstFile.Write(data); err != nil {
			log.Printf("COPY_WRITE_ERROR: %v", err)
			http.Error(w, "Error writing destination file", http.StatusInternalServerError)
			return
		}

		w.WriteHeader(http.StatusOK)
		log.Printf("FILE_COPIED: %s -> %s (%d bytes)", req.Src, req.Dst, len(data))
	}
}

// handleDiff produces a unified diff (3-line context) of two files in the workspace.
// GET /diff?a=<path>&b=<path>
// Returns 200 with empty body if identical, 200 with diff text if different,
// 400 for missing params, 404 for missing files, 500 for read errors.
func handleDiff(rootDir *os.Root, token string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !verifyToken(r, token) {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}

		aPath := r.URL.Query().Get("a")
		bPath := r.URL.Query().Get("b")
		if aPath == "" || bPath == "" {
			http.Error(w, "Bad Request: a and b are required", http.StatusBadRequest)
			return
		}

		readLines := func(path string) ([]string, error) {
			f, err := rootDir.Open(path)
			if err != nil {
				return nil, err
			}
			defer f.Close()
			var lines []string
			scanner := bufio.NewScanner(f)
			for scanner.Scan() {
				lines = append(lines, scanner.Text())
			}
			return lines, scanner.Err()
		}

		aLines, err := readLines(aPath)
		if err != nil {
			http.Error(w, "File not found: a", http.StatusNotFound)
			return
		}
		bLines, err := readLines(bPath)
		if err != nil {
			http.Error(w, "File not found: b", http.StatusNotFound)
			return
		}

		diff := computeUnifiedDiff(aLines, bLines, aPath, bPath)
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(diff))
	}
}

// computeUnifiedDiff returns a unified diff string with 3-line context.
// Returns empty string if files are identical.
func computeUnifiedDiff(aLines, bLines []string, aName, bName string) string {
	type editOp byte
	const (
		opEqual  editOp = '='
		opInsert editOp = '+'
		opDelete editOp = '-'
	)
	type edit struct {
		op   editOp
		line string
	}

	m, n := len(aLines), len(bLines)

	// Build LCS DP table
	dp := make([][]int, m+1)
	for i := range dp {
		dp[i] = make([]int, n+1)
	}
	for i := 1; i <= m; i++ {
		for j := 1; j <= n; j++ {
			if aLines[i-1] == bLines[j-1] {
				dp[i][j] = dp[i-1][j-1] + 1
			} else if dp[i-1][j] >= dp[i][j-1] {
				dp[i][j] = dp[i-1][j]
			} else {
				dp[i][j] = dp[i][j-1]
			}
		}
	}

	// Trace back to produce edits
	edits := make([]edit, 0, m+n)
	i, j := m, n
	for i > 0 || j > 0 {
		switch {
		case i > 0 && j > 0 && aLines[i-1] == bLines[j-1]:
			edits = append(edits, edit{opEqual, aLines[i-1]})
			i--
			j--
		case j > 0 && (i == 0 || dp[i][j-1] >= dp[i-1][j]):
			edits = append(edits, edit{opInsert, bLines[j-1]})
			j--
		default:
			edits = append(edits, edit{opDelete, aLines[i-1]})
			i--
		}
	}
	// Reverse
	for l, r := 0, len(edits)-1; l < r; l, r = l+1, r-1 {
		edits[l], edits[r] = edits[r], edits[l]
	}

	// Check if all equal
	allEqual := true
	for _, e := range edits {
		if e.op != opEqual {
			allEqual = false
			break
		}
	}
	if allEqual {
		return ""
	}

	const ctx = 3

	// Find changed edit indices
	type hunk struct {
		start, end int // indices into edits slice (inclusive)
	}
	var hunks []hunk
	for idx := 0; idx < len(edits); idx++ {
		if edits[idx].op != opEqual {
			s := idx - ctx
			if s < 0 {
				s = 0
			}
			e := idx + ctx
			// Extend to cover all changes within ctx of each other
			for e < len(edits) {
				if edits[e].op != opEqual {
					e += ctx + 1
				} else {
					e++
				}
				if e-idx > 2*ctx+1 {
					// check if there's a nearby change
					hasChange := false
					for k := idx + 1; k <= e && k < len(edits); k++ {
						if edits[k].op != opEqual {
							hasChange = true
							break
						}
					}
					if !hasChange {
						break
					}
				}
			}
			// Actually use a simpler approach: extend until no change within ctx
			// Reset and redo
			_ = e
			break
		}
	}
	// Simpler hunk grouping: mark all changed positions, group those within 2*ctx of each other
	changed := make([]bool, len(edits))
	for idx, e := range edits {
		if e.op != opEqual {
			changed[idx] = true
		}
	}
	hunks = nil
	idx := 0
	for idx < len(edits) {
		if !changed[idx] {
			idx++
			continue
		}
		s := idx - ctx
		if s < 0 {
			s = 0
		}
		e := idx + ctx
		if e >= len(edits) {
			e = len(edits) - 1
		}
		// Extend while there's a change within ctx of current end
		for {
			extended := false
			for k := e + 1; k < len(edits) && k <= e+ctx; k++ {
				if changed[k] {
					e = k + ctx
					if e >= len(edits) {
						e = len(edits) - 1
					}
					extended = true
				}
			}
			if !extended {
				break
			}
		}
		hunks = append(hunks, hunk{s, e})
		idx = e + 1
	}

	// Build output
	var sb strings.Builder
	sb.WriteString("--- a/")
	sb.WriteString(aName)
	sb.WriteByte('\n')
	sb.WriteString("+++ b/")
	sb.WriteString(bName)
	sb.WriteByte('\n')

	for _, h := range hunks {
		// Count old/new line numbers and spans
		aStart, aCount, bStart, bCount := 0, 0, 0, 0
		// Compute aStart/bStart: count lines before h.start
		for k := 0; k < h.start; k++ {
			if edits[k].op == opEqual || edits[k].op == opDelete {
				aStart++
			}
			if edits[k].op == opEqual || edits[k].op == opInsert {
				bStart++
			}
		}
		for k := h.start; k <= h.end; k++ {
			if edits[k].op == opEqual || edits[k].op == opDelete {
				aCount++
			}
			if edits[k].op == opEqual || edits[k].op == opInsert {
				bCount++
			}
		}
		sb.WriteString("@@ -")
		sb.WriteString(itoa(aStart + 1))
		sb.WriteByte(',')
		sb.WriteString(itoa(aCount))
		sb.WriteString(" +")
		sb.WriteString(itoa(bStart + 1))
		sb.WriteByte(',')
		sb.WriteString(itoa(bCount))
		sb.WriteString(" @@\n")
		for k := h.start; k <= h.end; k++ {
			switch edits[k].op {
			case opEqual:
				sb.WriteByte(' ')
			case opInsert:
				sb.WriteByte('+')
			case opDelete:
				sb.WriteByte('-')
			}
			sb.WriteString(edits[k].line)
			sb.WriteByte('\n')
		}
	}
	return sb.String()
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	buf := [20]byte{}
	pos := len(buf)
	for n > 0 {
		pos--
		buf[pos] = byte('0' + n%10)
		n /= 10
	}
	return string(buf[pos:])
}

// setupRouter isolates the routing logic so it can be tested independently
func setupRouter(rootDir *os.Root, token string) *http.ServeMux {
	mux := http.NewServeMux()

	mux.HandleFunc("/read", handleRead(rootDir, token))

	// Remove File
	mux.HandleFunc("/remove", handleRemove(rootDir, token))

	// Create Empty File
	mux.HandleFunc("/create", handleCreate(rootDir, token))

	// replace file content
	mux.HandleFunc("/write", handleWrite(rootDir, token))

	// list files
	mux.HandleFunc("/list", handleList(rootDir, token))

	// grep across all files
	mux.HandleFunc("/grep", handleGrep(rootDir, token))

	// replace string in file
	mux.HandleFunc("/replace", handleReplace(rootDir, token))

	// append to file
	mux.HandleFunc("/append", handleAppend(rootDir, token))

	// create directory
	mux.HandleFunc("/mkdir", handleMkdir(rootDir, token))

	// copy file
	mux.HandleFunc("/copy", handleCopy(rootDir, token))

	// diff two files
	mux.HandleFunc("/diff", handleDiff(rootDir, token))

	return mux
}

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

	// ConstantTimeCompare requires equal lengths
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

	rootDir, err := os.OpenRoot("/workspace")
	if err != nil {
		log.Fatalf("Failed to open root workspace: %v", err)
	}
	defer rootDir.Close()

	// Mount the isolated router
	mux := setupRouter(rootDir, token)

	server := &http.Server{
		Addr:    ":8443",
		Handler: mux,
		TLSConfig: &tls.Config{
			MinVersion: tls.VersionTLS13,
		},
	}

	log.Println("MCP Server listening on :8443 with TLS")
	log.Fatal(server.ListenAndServeTLS("/app/certs/mcp.crt", "/app/certs/mcp.key"))
}
