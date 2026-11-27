package main

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/wailsapp/wails/v3/pkg/application"
	"octop.desktop/internal/clientupdate"
)

const clientUpdateEventPrefix = "desktop:client-update:"

var managedClientUpdateID string
var nativeUpdateID = regexp.MustCompile(`^[0-9a-f]{32}$`)

type clientUpdateRequest struct {
	Request string `json:"request_id"`
	Job     string `json:"job_id"`
}
type clientUpdateListener struct{ api *App }

func currentClientBuild() clientupdate.Build {
	data, err := assets.ReadFile("assets/client-update-build.json")
	if err != nil {
		return clientupdate.Build{}
	}
	var build clientupdate.Build
	_ = json.Unmarshal(data, &build)
	return build
}

func (listener *clientUpdateListener) DispatchWailsEvent(event *application.CustomEvent) {
	if event == nil || !strings.HasPrefix(event.Name, clientUpdateEventPrefix) {
		return
	}
	content, err := url.QueryUnescape(strings.TrimPrefix(event.Name, clientUpdateEventPrefix))
	if err != nil || len(content) > 300 {
		return
	}
	var request clientUpdateRequest
	if json.Unmarshal([]byte(content), &request) != nil || !nativeUpdateID.MatchString(request.Request) || !nativeUpdateID.MatchString(request.Job) {
		return
	}
	go func() {
		err := listener.api.StartClientUpdate(request.Job)
		result := map[string]any{"request_id": request.Request, "ok": err == nil}
		if err != nil {
			result["error_code"] = "CLIENT_UPDATE_FAILED"
		}
		data, _ := json.Marshal(result)
		listener.api.window.ExecJS("window.dispatchEvent(new CustomEvent('octop:client-update-result',{detail:" + string(data) + "}))")
	}()
}

func (a *App) StartClientUpdate(identifier string) error {
	job, err := clientupdate.ReadJob(octopHome(), identifier)
	if err != nil {
		return err
	}
	build := currentClientBuild()
	if _, err = clientupdate.ValidateJob(job, build, time.Now()); err != nil {
		return err
	}
	executable, err := os.Executable()
	if err != nil {
		return err
	}
	root, err := clientupdate.ProgramRoot(executable)
	if err != nil {
		return err
	}
	if root != job.AppRoot || filepath.Clean(octopHome()) != job.DataRoot {
		return errors.New("update belongs to another local installation")
	}
	databasePath, sqlite, err := desktopSQLitePath(octopHome())
	resolvedDatabase, resolveErr := filepath.EvalSymlinks(databasePath)
	relative, relativeErr := filepath.Rel(filepath.Clean(octopHome()), resolvedDatabase)
	if err != nil || !sqlite || resolveErr != nil || relativeErr != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) {
		return errors.New("external database requires manual installation")
	}
	a.mu.Lock()
	if a.clientUpdating || a.cmd == nil || a.cmd.Process == nil {
		a.mu.Unlock()
		return errors.New("the desktop does not own an idle backend")
	}
	a.clientUpdating = true
	job.OldPID = os.Getpid()
	job.OldBackendPID = a.cmd.Process.Pid
	a.mu.Unlock()
	defer func() {
		if err != nil {
			a.mu.Lock()
			a.clientUpdating = false
			a.mu.Unlock()
		}
	}()
	directory, _ := clientupdate.JobDir(octopHome(), identifier)
	helper := filepath.Join(directory, filepath.Base(clientupdate.Helper(root, job.Platform)))
	content, err := os.ReadFile(clientupdate.Helper(root, job.Platform))
	if err != nil {
		return err
	}
	if err = clientupdate.AtomicWrite(helper, content, 0700); err != nil {
		return err
	}
	if err = clientupdate.SaveJob(job); err != nil {
		return err
	}
	command := exec.Command(helper, "--home", job.DataRoot, "--job", identifier)
	if err = command.Start(); err != nil {
		return err
	}
	active, _ := json.Marshal(map[string]any{"job_id": identifier, "helper_pid": command.Process.Pid})
	if err = clientupdate.AtomicWrite(filepath.Join(octopHome(), "client-updates", "active.json"), active, 0600); err != nil {
		return err
	}
	go func() { _ = command.Wait() }()
	go a.monitorClientUpdate(identifier)
	return nil
}

func (a *App) monitorClientUpdate(identifier string) {
	time.Sleep(300 * time.Millisecond)
	// Keep a small native-hosted progress surface alive while the helper backs
	// up data. The backend can stop without leaving a frozen chat window.
	a.window.SetURL("/")
	a.mu.Lock()
	backend := a.cmd
	a.cmd = nil
	a.mu.Unlock()
	stopOctop(backend)
	for {
		job, err := clientupdate.ReadJob(octopHome(), identifier)
		if err != nil {
			a.requestQuit()
			return
		}
		text := clientUpdateText(a.store.get().Locale, job.Phase)
		a.setStatus(text)
		if job.Phase == "ready_to_swap" {
			a.requestQuit()
			return
		}
		if job.Phase == "failed" || job.Phase == "rolled_back" {
			a.mu.Lock()
			a.clientUpdating = false
			a.mu.Unlock()
			a.boot()
			return
		}
		time.Sleep(250 * time.Millisecond)
	}
}

func clientUpdateText(locale Locale, phase string) string {
	zh := map[string]string{"applying": "正在准备更新…", "backing_up": "正在备份账号、聊天和配置…", "installing": "正在安装企业新版…", "ready_to_swap": "备份完成，即将重启更新…", "starting": "正在验证新版启动…", "rolling_back": "更新未完成，正在恢复上一版本…"}
	en := map[string]string{"applying": "Preparing the update…", "backing_up": "Backing up accounts, chats and settings…", "installing": "Installing the company update…", "ready_to_swap": "Backup complete. Restarting to update…", "starting": "Verifying the new client…", "rolling_back": "Restoring the previous client…"}
	if locale == LocaleZH {
		if value := zh[phase]; value != "" {
			return value
		}
		return "正在更新 Octop…"
	}
	if value := en[phase]; value != "" {
		return value
	}
	return "Updating Octop…"
}

func (a *App) completeManagedCandidate(base string) error {
	if managedClientUpdateID == "" {
		return nil
	}
	job, err := clientupdate.ReadJob(octopHome(), managedClientUpdateID)
	if err != nil {
		return err
	}
	if job.Phase != "starting" || job.CandidatePID != os.Getpid() {
		return errors.New("candidate no longer owns startup")
	}
	build := currentClientBuild()
	release, err := clientupdate.Verify(job.Envelope, build.Authority)
	if err != nil || release.Version != build.Version || job.TargetVersion != build.Version {
		return errors.New("candidate update identity mismatch")
	}
	a.mu.Lock()
	if a.cmd != nil && a.cmd.Process != nil {
		job.BackendPID = a.cmd.Process.Pid
	}
	a.mu.Unlock()
	job.CandidatePID = os.Getpid()
	job.CandidateBase = base
	job.Phase = "candidate_ready"
	if err = clientupdate.SaveJob(job); err != nil {
		return err
	}
	deadline := time.Now().Add(4 * time.Minute)
	for time.Now().Before(deadline) {
		current, readErr := clientupdate.ReadJob(octopHome(), managedClientUpdateID)
		if readErr != nil {
			return readErr
		}
		if current.Phase == "accepted" {
			client := http.Client{Timeout: 5 * time.Second}
			response, getErr := client.Get(base + "/api/health")
			if getErr == nil {
				var health struct {
					Pending bool `json:"client_update_pending"`
				}
				decodeErr := json.NewDecoder(response.Body).Decode(&health)
				response.Body.Close()
				if decodeErr == nil && !health.Pending {
					managedClientUpdateID = ""
					return nil
				}
			}
		}
		if current.Phase == "rolling_back" || current.Phase == "rolled_back" || current.Phase == "failed" {
			return errors.New("candidate was not accepted")
		}
		time.Sleep(250 * time.Millisecond)
	}
	return errors.New("update acceptance timed out")
}

func initializeClientUpdater() bool {
	for index, value := range os.Args {
		if value == "--managed-client-update" && index+1 < len(os.Args) {
			managedClientUpdateID = os.Args[index+1]
		}
	}
	if managedClientUpdateID != "" {
		if !nativeUpdateID.MatchString(managedClientUpdateID) {
			return false
		}
		if job, err := clientupdate.ReadJob(octopHome(), managedClientUpdateID); err == nil && (job.Phase == "accepted" || job.Phase == "rolled_back" || job.Phase == "cancelled") {
			managedClientUpdateID = ""
			return true
		}
		job, err := clientupdate.ReadJob(octopHome(), managedClientUpdateID)
		build := currentClientBuild()
		if err != nil {
			return false
		}
		release, verifyErr := clientupdate.Verify(job.Envelope, build.Authority)
		if verifyErr != nil || release.Version != build.Version || job.TargetVersion != build.Version || job.Phase != "starting" {
			return false
		}
		job.CandidatePID = os.Getpid()
		if clientupdate.SaveJob(job) != nil {
			return false
		}
		return true
	}
	data, err := os.ReadFile(filepath.Join(octopHome(), "client-updates", "active.json"))
	if err != nil {
		return true
	}
	var active struct {
		Job string `json:"job_id"`
		PID int    `json:"helper_pid"`
	}
	if json.Unmarshal(data, &active) != nil || !nativeUpdateID.MatchString(active.Job) {
		return true
	}
	job, err := clientupdate.ReadJob(octopHome(), active.Job)
	if err != nil {
		return true
	}
	if job.Phase == "accepted" || job.Phase == "rolled_back" || job.Phase == "cancelled" || (job.Phase == "failed" && (job.ErrorCode == nil || *job.ErrorCode != "CLIENT_UPDATE_RECOVERY_REQUIRED")) {
		return true
	}
	if clientupdate.ProcessAlive(active.PID) {
		return false
	}
	if !job.BackupReady {
		return true
	}
	helper := clientupdate.Helper(job.AppRoot, job.Platform)
	command := exec.Command(helper, "--home", job.DataRoot, "--job", job.ID, "--recover", "--wait-pid", strconv.Itoa(os.Getpid()))
	if command.Start() == nil {
		return false
	}
	// Do not admit user work while a backed-up, uncommitted installation
	// still needs recovery. The retained journal and snapshot are recoverable.
	return false
}

func desktopBootstrapURL(base, version string) string {
	parsed, err := url.Parse(base)
	if err != nil || parsed.Scheme != "http" || (parsed.Hostname() != "127.0.0.1" && parsed.Hostname() != "localhost") {
		return base
	}
	return strings.TrimRight(base, "/") + "/api/client-updates/bootstrap?version=" + url.QueryEscape(version)
}

func recordCandidateBackend(pid int) error {
	if managedClientUpdateID == "" {
		return nil
	}
	job, err := clientupdate.ReadJob(octopHome(), managedClientUpdateID)
	if err != nil {
		return err
	}
	if job.CandidatePID != os.Getpid() || job.Phase != "starting" {
		return errors.New("candidate startup was revoked")
	}
	job.BackendPID = pid
	return clientupdate.SaveJob(job)
}
