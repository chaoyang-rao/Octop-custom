package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

const freePortScanLimit = 100

type noFreePortError struct {
	From int
	To   int
}

func (e noFreePortError) Error() string {
	return fmt.Sprintf("no free port from %d to %d", e.From, e.To)
}

type cannotBindError struct {
	Host string
	Port int
	Err  error
}

func (e cannotBindError) Error() string {
	return e.Err.Error()
}

func (e cannotBindError) Unwrap() error { return e.Err }

func mustEnv(cmd *exec.Cmd, extra map[string]string) {
	cmd.Env = overlayEnv(os.Environ(), extra)
}

func overlayEnv(base []string, extra map[string]string) []string {
	out := make([]string, 0, len(base)+len(extra))
	for _, entry := range base {
		key, _, ok := strings.Cut(entry, "=")
		if ok {
			if _, replaced := extra[key]; replaced {
				continue
			}
		}
		out = append(out, entry)
	}
	for key, value := range extra {
		out = append(out, key+"="+value)
	}
	return out
}

func startOctop(root string, port int) (*exec.Cmd, error) {
	py := pythonExe(root)
	launch := filepath.Join(root, "launch.py")
	// Omit --host/--port. `octop run` writes those flags back to config.json.
	// OCTOP_PORT selects the free port for this process and is not saved.
	cmd := exec.Command(py, launch, "run")
	cmd.Dir = root
	mustEnv(cmd, map[string]string{
		"OCTOP_HOME":           octopHome(),
		"OCTOP_GREEN_PACKAGES": filepath.Join(root, "packages"),
		"OCTOP_CUSTOM_BUILD":   "1",
		"OCTOP_PORT":           strconv.Itoa(port),
		"PYTHONNOUSERSITE":     "1",
		"PYTHONPATH":           "",
	})
	configureProcGroup(cmd)
	if runtime.GOOS == "linux" {
		// The Linux desktop release has no server terminal; the shell owns status
		// presentation just like the Windows GUI executable.
		cmd.Stdout = io.Discard
		cmd.Stderr = io.Discard
	} else if runtime.GOOS != "windows" {
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
	}
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	return cmd, nil
}

func stopOctop(cmd *exec.Cmd) {
	if cmd == nil || cmd.Process == nil {
		return
	}
	killProcessTree(cmd)
}

const desktopPortFileName = "custom-desktop-port"

func desktopPortPath() string {
	return filepath.Join(octopHome(), desktopPortFileName)
}

func readDesktopPort() (int, bool) {
	data, err := os.ReadFile(desktopPortPath())
	if err != nil {
		return 0, false
	}
	port, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil || port < 1 || port > 65535 {
		return 0, false
	}
	return port, true
}

func writeDesktopPort(port int) error {
	if port < 1 || port > 65535 {
		return fmt.Errorf("invalid desktop port %d", port)
	}
	return os.WriteFile(desktopPortPath(), []byte(strconv.Itoa(port)), 0o644)
}

func clearDesktopPort() {
	_ = os.Remove(desktopPortPath())
}

var errIncompatibleDashboard = errors.New("another Octop runtime is using the account data")

// Probe before extracting: replacing a live runtime may fail on Windows and
// changes files beneath an active agent on other systems.
func prepareDesktopRuntime(locale Locale, status func(string)) (string, error) {
	expected, err := bundledPortableIdentity()
	if err != nil {
		return "", err
	}
	host, preferred := resolveListen()
	existing, err := findRunningDashboard(host, preferred, expected)
	if err != nil {
		return "", fmt.Errorf("%s", desktopText(locale, copyErrorRuntimeConflict))
	}
	if existing != "" {
		return existing, nil
	}
	return "", ensurePortable(locale, status)
}

// Reuse only a compatible custom backend at the configured or remembered port.
// A conflicting backend must be quit by its owner, never killed by this shell.
func findRunningDashboard(host string, preferred int, expected runtimeIdentity) (string, error) {
	ports := []int{preferred}
	if port, ok := readDesktopPort(); ok && port != preferred {
		ports = append(ports, port)
	}
	for _, port := range ports {
		base := dashboardURL(host, port)
		running, version := dashboardHealth(base)
		if !running {
			continue
		}
		if version == "" || compareVersions(version, expected.Version) < 0 || !dashboardLoginMatches(base, expected.Authority) {
			return "", errIncompatibleDashboard
		}
		return base, nil
	}
	return "", nil
}

func dashboardLoginMatches(base, authority string) bool {
	client := &http.Client{Timeout: 800 * time.Millisecond}
	resp, err := client.Get(strings.TrimRight(base, "/") + "/api/setup/status")
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return false
	}
	var payload struct {
		EnterpriseLogin bool   `json:"enterprise_login"`
		Authority       string `json:"enterprise_authority_url"`
	}
	if json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&payload) != nil {
		return false
	}
	return payload.EnterpriseLogin == (authority != "") &&
		strings.TrimRight(payload.Authority, "/") == strings.TrimRight(authority, "/")
}

func resolveDashboardURL() string {
	host, port := resolveListen()
	return dashboardURL(host, port)
}

func resolveListen() (string, int) {
	host := "127.0.0.1"
	port := 8088
	if data, err := os.ReadFile(filepath.Join(octopHome(), "config.json")); err == nil {
		var raw struct {
			BindHost string `json:"bind_host"`
			Host     string `json:"host"`
			Port     *int   `json:"port"`
		}
		if json.Unmarshal(data, &raw) == nil {
			switch {
			case raw.BindHost != "":
				host = raw.BindHost
			case raw.Host != "":
				host = raw.Host
			}
			if raw.Port != nil && *raw.Port > 0 && *raw.Port <= 65535 {
				port = *raw.Port
			}
		}
	}
	if v := strings.TrimSpace(os.Getenv("OCTOP_BIND_HOST")); v != "" {
		host = v
	}
	if v := strings.TrimSpace(os.Getenv("OCTOP_PORT")); v != "" {
		if parsed, err := strconv.Atoi(v); err == nil && parsed > 0 && parsed <= 65535 {
			port = parsed
		}
	}
	return host, port
}

func chooseFreePort(host string, start int) (int, error) {
	return firstFreePort(start, func(port int) (bool, error) {
		inUse, err := listenProbe(host, port)
		if err != nil {
			return false, cannotBindError{Host: probeHost(host), Port: port, Err: err}
		}
		return inUse, nil
	})
}

func firstFreePort(start int, probe func(int) (bool, error)) (int, error) {
	if start < 1 || start > 65535 {
		start = 8088
	}
	last := start + freePortScanLimit - 1
	if last > 65535 {
		last = 65535
	}
	for port := start; port <= last; port++ {
		inUse, err := probe(port)
		if err != nil {
			return 0, err
		}
		if !inUse {
			return port, nil
		}
	}
	return 0, noFreePortError{From: start, To: last}
}

func listenProbe(host string, port int) (bool, error) {
	ln, err := net.Listen("tcp", net.JoinHostPort(probeHost(host), strconv.Itoa(port)))
	if err == nil {
		_ = ln.Close()
		return false, nil
	}
	if isAddrInUse(err) {
		return true, nil
	}
	return false, err
}

func octopAlreadyRunning(base string) bool {
	running, _ := dashboardHealth(base)
	return running
}

func customOctopAlreadyRunning(base string) bool {
	_, custom := dashboardHealth(base)
	return custom != ""
}

func dashboardHealth(base string) (bool, string) {
	client := &http.Client{Timeout: 800 * time.Millisecond}
	url := strings.TrimRight(base, "/") + "/api/health"
	resp, err := client.Get(url)
	if err != nil {
		return false, ""
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return false, ""
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return false, ""
	}
	var payload struct {
		OK            bool            `json:"ok"`
		UsersLoaded   json.RawMessage `json:"users_loaded"`
		AgentsRunning json.RawMessage `json:"agents_running"`
		CustomRelease string          `json:"custom_release"`
	}
	if json.Unmarshal(body, &payload) != nil {
		return false, ""
	}
	running := payload.OK && len(payload.UsersLoaded) > 0 && len(payload.AgentsRunning) > 0
	if !running {
		return false, ""
	}
	return true, payload.CustomRelease
}

func probeHost(host string) string {
	host = strings.TrimSpace(host)
	host = strings.Trim(host, "[]")
	if host == "" {
		return "127.0.0.1"
	}
	return host
}

func dashboardURL(host string, port int) string {
	switch host {
	case "0.0.0.0", "::", "[::]":
		host = "127.0.0.1"
	}
	if strings.Contains(host, ":") && !strings.HasPrefix(host, "[") {
		host = "[" + host + "]"
	}
	return fmt.Sprintf("http://%s:%d/", host, port)
}
