package clientupdate

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

type Installer struct {
	Job          *Job
	Build        Build
	Launch       func(string, []string, []string) (int, error)
	ReadyTimeout time.Duration
}

func (installer *Installer) phase(value string) error {
	installer.Job.Phase = value
	return SaveJob(installer.Job)
}
func (installer *Installer) directories() (string, string) {
	job := installer.Job
	directory, _ := JobDir(job.DataRoot, job.ID)
	stage := ".OctopCustom-stage-" + job.ID
	if installer.Build.Product == CompanionProduct {
		stage = ".Dora-stage-" + job.ID
	}
	if strings.HasPrefix(job.Platform, "darwin-") {
		stage += ".app"
	}
	return directory, filepath.Join(filepath.Dir(job.AppRoot), stage)
}
func waitGone(ctx context.Context, pid int) error {
	for ProcessAlive(pid) {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(100 * time.Millisecond):
		}
	}
	return nil
}
func (installer *Installer) Install(ctx context.Context) error {
	job := installer.Job
	directory, stage := installer.directories()
	item, err := ValidateJob(job, installer.Build, time.Now())
	if err != nil {
		return err
	}
	if !filepath.IsAbs(job.AppRoot) || filepath.IsAbs(job.AppRoot) && filepath.Dir(job.AppRoot) == job.AppRoot || !filepath.IsAbs(job.DataRoot) || inside(job.AppRoot, job.DataRoot) {
		return errors.New("invalid local installation paths")
	}
	info, err := os.Lstat(job.AppRoot)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return errors.New("invalid installed application")
	}
	probe, err := os.CreateTemp(filepath.Dir(job.AppRoot), ".octop-write-probe-*")
	if err != nil {
		return err
	}
	probe.Close()
	os.Remove(probe.Name())
	sha, size, err := HashFile(filepath.Join(directory, "payload.zip"))
	if err != nil || sha != item.SHA256 || size != item.Size {
		return errors.New("invalid downloaded update")
	}
	if _, err = os.Lstat(stage); !os.IsNotExist(err) {
		return errors.New("unfinished installation stage")
	}
	backendContext, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	if err = waitGone(backendContext, job.OldBackendPID); err != nil {
		return err
	}
	programSize, err := TreeSize(job.AppRoot, nil)
	if err != nil {
		return err
	}
	dataSize, err := TreeSize(job.DataRoot, DataExcluded)
	if err != nil {
		return err
	}
	available, err := FreeSpace(job.DataRoot)
	if err != nil || available < dataSize+programSize+uint64(item.Size)*3+(128<<20) {
		return errors.New("insufficient update space")
	}
	appSpace, spaceErr := FreeSpace(filepath.Dir(job.AppRoot))
	if spaceErr != nil || appSpace < uint64(item.Size)*4 {
		return errors.New("insufficient application volume space")
	}
	if err = installer.phase("backing_up"); err != nil {
		return err
	}
	backup := filepath.Join(directory, "backup", "data")
	if err = CopyTree(job.DataRoot, backup, DataExcluded); err != nil {
		return err
	}
	if err = CopyTree(job.AppRoot, filepath.Join(directory, "backup", "program"), nil); err != nil {
		return err
	}
	job.BackupReady = true
	if err = SaveJob(job); err != nil {
		return err
	}
	if err = ExtractPackageForProduct(filepath.Join(directory, "payload.zip"), stage, job.Platform, installer.Build.Product); err != nil {
		return err
	}
	candidate, err := LoadBuildForProduct(stage, job.Platform, installer.Build.Product)
	if err != nil || candidate.Version != job.TargetVersion || candidate.Authority != installer.Build.Authority {
		return errors.New("candidate build mismatch")
	}
	if strings.HasPrefix(job.Platform, "darwin-") {
		if err = exec.Command("/usr/bin/codesign", "--verify", "--deep", "--strict", stage).Run(); err != nil {
			return errors.New("candidate signature invalid")
		}
	}
	if strings.HasPrefix(job.Platform, "windows-") {
		uninstaller := filepath.Join(job.AppRoot, "uninstall.exe")
		if content, readErr := os.ReadFile(uninstaller); readErr == nil {
			if err = os.WriteFile(filepath.Join(stage, "uninstall.exe"), content, 0755); err != nil {
				return err
			}
		}
	}
	if err = installer.phase("ready_to_swap"); err != nil {
		return err
	}
	oldContext, cancelOld := context.WithTimeout(ctx, 45*time.Second)
	defer cancelOld()
	if err = waitGone(oldContext, job.OldPID); err != nil {
		return err
	}
	if err = installer.phase("installing"); err != nil {
		return err
	}
	if err = replaceProgramForProduct(stage, job.AppRoot, job.Platform, installer.Build.Product); err != nil {
		return err
	}
	job.ProgramMoved = true
	if err = SaveJob(job); err != nil {
		return err
	}
	if err = installer.phase("starting"); err != nil {
		return err
	}
	launch := installer.Launch
	if launch == nil {
		launch = launchApplication
	}
	pid, err := launch(ExecutableForProduct(job.AppRoot, job.Platform, installer.Build.Product), []string{"--managed-client-update", job.ID}, withHome(os.Environ(), job.DataRoot))
	if err != nil {
		return err
	}
	// The candidate journals its own PID before starting its backend. Do not
	// overwrite that journal with the helper's older copy after exec.Start.
	job.CandidatePID = pid
	timeout := installer.ReadyTimeout
	if timeout == 0 {
		timeout = 3 * time.Minute
	}
	readyContext, cancelReady := context.WithTimeout(ctx, timeout)
	defer cancelReady()
	for {
		current, readErr := ReadJob(job.DataRoot, job.ID)
		if readErr == nil && current.Phase == "candidate_ready" {
			if current.CandidatePID != pid || !candidateHealthyForProduct(current, installer.Build.Product) {
				return errors.New("candidate readiness mismatch")
			}
			installer.Job = current
			return installer.phase("accepted")
		}
		if !ProcessAlive(pid) {
			return errors.New("candidate exited before readiness")
		}
		select {
		case <-readyContext.Done():
			return readyContext.Err()
		case <-time.After(250 * time.Millisecond):
		}
	}
}

func candidateHealthy(job *Job) bool {
	return candidateHealthyForProduct(job, Product)
}
func candidateHealthyForProduct(job *Job, product string) bool {
	root := strings.TrimSuffix(job.CandidateBase, "/")
	base, err := url.Parse(root)
	if err != nil || base.Scheme != "http" || base.Hostname() != "127.0.0.1" || base.Port() == "" || base.User != nil || base.Path != "" || base.RawQuery != "" {
		return false
	}
	client := &http.Client{Timeout: 5 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	endpoint := "/api/health"
	if product == CompanionProduct {
		endpoint += "/companion"
	}
	response, err := client.Get(root + endpoint)
	if err != nil {
		return false
	}
	defer response.Body.Close()
	var health struct {
		OK               bool   `json:"ok"`
		Version          string `json:"custom_release"`
		Pending          bool   `json:"client_update_pending"`
		Companion        bool   `json:"companion"`
		CompanionVersion string `json:"companion_version"`
	}
	if response.StatusCode != 200 || json.NewDecoder(response.Body).Decode(&health) != nil || !health.Pending {
		return false
	}
	if product == CompanionProduct {
		return health.Companion && health.CompanionVersion == job.TargetVersion
	}
	return health.OK && health.Version == job.TargetVersion
}

func (installer *Installer) Rollback(ctx context.Context) error {
	job := installer.Job
	directory, stage := installer.directories()
	if current, err := ReadJob(job.DataRoot, job.ID); err == nil {
		if current.Phase == "accepted" {
			return errors.New("accepted updates cannot restore old user data")
		}
		job.CandidatePID = current.CandidatePID
		job.BackendPID = current.BackendPID
	}
	job.Phase = "rolling_back"
	_ = SaveJob(job)
	if job.CandidatePID > 0 {
		_ = TerminateProcess(job.CandidatePID)
	}
	if job.BackendPID > 0 {
		_ = TerminateProcess(job.BackendPID)
	}
	for _, pid := range []int{job.CandidatePID, job.BackendPID} {
		if pid > 0 {
			if err := waitGone(ctx, pid); err != nil {
				return err
			}
		}
	}
	if job.BackupReady {
		_ = os.RemoveAll(stage)
		if err := CopyTree(filepath.Join(directory, "backup", "program"), stage, nil); err != nil {
			return err
		}
		if err := replaceProgramForProduct(stage, job.AppRoot, job.Platform, installer.Build.Product); err != nil {
			return err
		}
	}
	if job.BackupReady {
		if err := RestoreData(filepath.Join(directory, "backup", "data"), job.DataRoot); err != nil {
			return err
		}
	}
	_ = os.RemoveAll(stage)
	job.Phase = "rolled_back"
	code := "CLIENT_UPDATE_FAILED"
	job.ErrorCode = &code
	if err := SaveJob(job); err != nil {
		return err
	}
	launch := installer.Launch
	if launch == nil {
		launch = launchApplication
	}
	_, err := launch(ExecutableForProduct(job.AppRoot, job.Platform, installer.Build.Product), nil, withHome(os.Environ(), job.DataRoot))
	return err
}

func replaceProgram(candidate, target, platform string) error {
	return replaceProgramForProduct(candidate, target, platform, Product)
}
func replaceProgramForProduct(candidate, target, platform, product string) error {
	if strings.HasPrefix(platform, "darwin-") {
		return swapDirectories(candidate, target)
	}
	if product == CompanionProduct {
		// The native host waits outside the application while its backend and
		// input renderer stop. Keep Dora.exe as the final atomic replacement.
		err := filepath.WalkDir(candidate, func(path string, entry os.DirEntry, walkErr error) error {
			if walkErr != nil {
				return walkErr
			}
			relative, err := filepath.Rel(candidate, path)
			if err != nil {
				return err
			}
			if relative == "." || relative == "Dora.exe" {
				return nil
			}
			destination := filepath.Join(target, relative)
			if entry.IsDir() {
				if info, err := os.Lstat(destination); err == nil && info.Mode()&os.ModeSymlink != 0 {
					return errors.New("linked Windows installation directory")
				}
				return os.MkdirAll(destination, 0755)
			}
			info, err := entry.Info()
			if err != nil || !info.Mode().IsRegular() {
				return errors.New("invalid Windows companion entry")
			}
			data, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			return AtomicWrite(destination, data, info.Mode().Perm())
		})
		if err != nil {
			return err
		}
		data, err := os.ReadFile(filepath.Join(candidate, "Dora.exe"))
		if err != nil {
			return err
		}
		return AtomicWrite(filepath.Join(target, "Dora.exe"), data, 0755)
	}
	// Windows packages contain exactly these files. Replace the executable last,
	// atomically, so a crash cannot remove the application's launch path.
	for _, name := range []string{"client-updater.exe", "client-update-build.json", "OctopCustom.exe"} {
		content, err := os.ReadFile(filepath.Join(candidate, name))
		if err != nil {
			return err
		}
		if err = AtomicWrite(filepath.Join(target, name), content, 0755); err != nil {
			return err
		}
	}
	return nil
}

func launchApplication(executable string, args, environment []string) (int, error) {
	command := exec.Command(executable, args...)
	command.Env = environment
	if err := command.Start(); err != nil {
		return 0, err
	}
	pid := command.Process.Pid
	go func() { _ = command.Wait() }()
	return pid, nil
}
func withHome(environment []string, home string) []string {
	result := make([]string, 0, len(environment)+1)
	for _, value := range environment {
		if !strings.HasPrefix(value, "OCTOP_HOME=") && !strings.HasPrefix(value, "OCTOP_CLIENT_UPDATE_PENDING=") {
			result = append(result, value)
		}
	}
	return append(result, "OCTOP_HOME="+home)
}

// Keep the package usable by Linux CI's filesystem tests; shipped clients are
// the three platforms checked in the signed protocol.
