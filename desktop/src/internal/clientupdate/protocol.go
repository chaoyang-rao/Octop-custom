// Package clientupdate is the non-GUI, fixed-protocol desktop installer.
package clientupdate

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	_ "embed"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"time"
)

//go:embed trust.json
var trustJSON []byte

const Product = "octop-desktop"
const Protocol = 1
const Repository = "chaoyang-rao/Octop-custom"
const BundleID = "com.chaoyangrao.octopcustom"

var jobIDPattern = regexp.MustCompile(`^[0-9a-f]{32}$`)
var digestPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)
var versionPattern = regexp.MustCompile(`^[A-Za-z0-9.+-]{1,80}$`)

type Envelope struct {
	KeyID     string `json:"key_id"`
	Payload   string `json:"payload"`
	Signature string `json:"signature"`
}
type Package struct {
	Platform string `json:"platform"`
	Filename string `json:"filename"`
	URL      string `json:"url"`
	SHA256   string `json:"sha256"`
	Size     int64  `json:"size"`
}
type Release struct {
	Schema       int       `json:"schema_version"`
	Protocol     int       `json:"protocol"`
	Authority    string    `json:"authority"`
	Revision     int       `json:"revision"`
	Version      string    `json:"version"`
	Tag          string    `json:"tag"`
	SourceCommit string    `json:"source_commit"`
	PublishedAt  int64     `json:"published_at"`
	Notes        string    `json:"notes"`
	Enabled      bool      `json:"enabled"`
	Subjects     []string  `json:"allowed_subjects"`
	Packages     []Package `json:"packages"`
}
type Build struct {
	Product   string `json:"product"`
	Protocol  int    `json:"protocol"`
	Version   string `json:"version"`
	Authority string `json:"authority"`
}
type Job struct {
	Schema         int      `json:"schema_version"`
	ID             string   `json:"id"`
	Owner          int      `json:"owner_user_id"`
	Subject        string   `json:"subject"`
	Platform       string   `json:"platform"`
	CurrentVersion string   `json:"current_version"`
	TargetVersion  string   `json:"target_version"`
	Revision       int      `json:"revision"`
	Phase          string   `json:"phase"`
	Downloaded     int64    `json:"downloaded_bytes"`
	Total          int64    `json:"total_bytes"`
	ErrorCode      *string  `json:"error_code"`
	Envelope       Envelope `json:"envelope"`
	ApprovedAt     int64    `json:"approved_at"`
	ExpiresAt      int64    `json:"expires_at"`
	AppRoot        string   `json:"app_root"`
	DataRoot       string   `json:"data_root"`
	OldPID         int      `json:"old_pid"`
	OldBackendPID  int      `json:"old_backend_pid"`
	CandidatePID   int      `json:"candidate_pid"`
	BackendPID     int      `json:"backend_pid"`
	CandidateBase  string   `json:"candidate_base"`
	BackupReady    bool     `json:"backup_ready"`
	ProgramMoved   bool     `json:"program_moved"`
}

func HostPlatform() string { return runtime.GOOS + "-" + runtime.GOARCH }

func decodeStrict(data []byte, value any) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(value); err != nil {
		return err
	}
	if decoder.Decode(new(any)) != io.EOF {
		return errors.New("extra JSON value")
	}
	return nil
}

func Verify(envelope Envelope, authority string) (Release, error) {
	return VerifyWithTrust(envelope, authority, trustJSON)
}
func VerifyWithTrust(envelope Envelope, authority string, trusted []byte) (Release, error) {
	var release Release
	var pins struct {
		Schema      int                          `json:"schema_version"`
		Authorities map[string]map[string]string `json:"authorities"`
	}
	if err := decodeStrict(trusted, &pins); err != nil || pins.Schema != 1 {
		return release, errors.New("invalid update trust")
	}
	key, err := base64.StdEncoding.DecodeString(pins.Authorities[authority][envelope.KeyID])
	if err != nil || len(key) != ed25519.PublicKeySize {
		return release, errors.New("unknown update signer")
	}
	data, err := base64.StdEncoding.DecodeString(envelope.Payload)
	if err != nil || len(data) > 375000 {
		return release, errors.New("invalid signed payload")
	}
	signature, err := base64.StdEncoding.DecodeString(envelope.Signature)
	if err != nil || !ed25519.Verify(key, data, signature) {
		return release, errors.New("invalid update signature")
	}
	if err := decodeStrict(data, &release); err != nil {
		return release, err
	}
	if release.Schema != 1 || release.Protocol != Protocol || release.Authority != authority || release.Revision < 1 || !release.Enabled || !versionPattern.MatchString(release.Version) {
		return release, errors.New("unsupported update metadata")
	}
	if !regexp.MustCompile(`^[0-9a-f]{40}$`).MatchString(release.SourceCommit) || len(release.Packages) != 3 || !strings.HasPrefix(release.Tag, "custom-") || strings.ContainsAny(release.Tag, "/\\?#") {
		return release, errors.New("invalid release identity")
	}
	seen := map[string]bool{}
	for _, item := range release.Packages {
		if item.Platform != "windows-amd64" && item.Platform != "darwin-amd64" && item.Platform != "darwin-arm64" {
			return release, errors.New("unsupported platform")
		}
		name := "OctopCustom-update-" + item.Platform + "-" + release.Version + ".zip"
		if seen[item.Platform] || item.Filename != name || item.URL != "https://github.com/"+Repository+"/releases/download/"+release.Tag+"/"+name || !digestPattern.MatchString(item.SHA256) || item.Size <= 0 || item.Size > 2<<30 {
			return release, errors.New("invalid update package")
		}
		seen[item.Platform] = true
	}
	return release, nil
}

func JobDir(home, id string) (string, error) {
	if !jobIDPattern.MatchString(id) {
		return "", errors.New("invalid update id")
	}
	directory := filepath.Join(home, "client-updates", "jobs", id)
	for _, path := range []string{filepath.Join(home, "client-updates"), filepath.Join(home, "client-updates", "jobs"), directory} {
		if info, err := os.Lstat(path); err == nil && info.Mode()&os.ModeSymlink != 0 {
			return "", errors.New("linked update directory")
		}
	}
	return directory, nil
}

func ReadJob(home, id string) (*Job, error) {
	directory, err := JobDir(home, id)
	if err != nil {
		return nil, err
	}
	path := filepath.Join(directory, "job.json")
	info, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Size() > 1000000 {
		return nil, errors.New("invalid update journal")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var job Job
	if err := decodeStrict(data, &job); err != nil {
		return nil, err
	}
	if job.ID != id || job.Schema != 1 || job.DataRoot != filepath.Clean(home) {
		return nil, errors.New("invalid update journal identity")
	}
	return &job, nil
}

func SaveJob(job *Job) error {
	directory, err := JobDir(job.DataRoot, job.ID)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(directory, 0700); err != nil {
		return err
	}
	data, err := json.Marshal(job)
	if err != nil {
		return err
	}
	return AtomicWrite(filepath.Join(directory, "job.json"), data, 0600)
}

func AtomicWrite(path string, data []byte, mode os.FileMode) error {
	file, err := os.CreateTemp(filepath.Dir(path), ".client-update-*")
	if err != nil {
		return err
	}
	name := file.Name()
	defer os.Remove(name)
	if err = file.Chmod(mode); err == nil {
		_, err = file.Write(data)
	}
	if err == nil {
		err = file.Sync()
	}
	closeErr := file.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	return replaceFile(name, path)
}

func ValidateJob(job *Job, build Build, now time.Time) (Package, error) {
	if job.Phase != "applying" || job.ExpiresAt < now.Unix() || job.ExpiresAt > now.Add(3*time.Minute).Unix() || job.Owner <= 0 || job.ApprovedAt <= 0 || job.CurrentVersion != build.Version || job.Platform != HostPlatform() {
		return Package{}, errors.New("expired or mismatched update approval")
	}
	release, err := Verify(job.Envelope, build.Authority)
	if err != nil {
		return Package{}, err
	}
	if !digestPattern.MatchString(job.Subject) || release.Version != job.TargetVersion || release.Revision != job.Revision || CompareVersions(release.Version, build.Version) <= 0 {
		return Package{}, errors.New("stale update target")
	}
	if len(release.Subjects) > 0 {
		permitted := false
		for _, subject := range release.Subjects {
			if subject == job.Subject {
				permitted = true
			}
		}
		if !permitted {
			return Package{}, errors.New("update audience mismatch")
		}
	}
	for _, item := range release.Packages {
		if item.Platform == job.Platform {
			return item, nil
		}
	}
	return Package{}, errors.New("missing platform package")
}

func HashFile(path string) (string, int64, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", 0, err
	}
	defer file.Close()
	digest := sha256.New()
	size, err := io.Copy(digest, file)
	return hex.EncodeToString(digest.Sum(nil)), size, err
}

func Fail(job *Job, code string) error {
	job.Phase = "failed"
	job.ErrorCode = &code
	return SaveJob(job)
}

func ProgramRoot(executable string) (string, error) {
	path, err := filepath.EvalSymlinks(executable)
	if err != nil {
		return "", err
	}
	if runtime.GOOS == "darwin" {
		root := filepath.Dir(filepath.Dir(filepath.Dir(path)))
		if filepath.Base(root) != "OctopCustom.app" {
			return "", errors.New("unexpected Mac application")
		}
		return root, nil
	}
	root := filepath.Dir(path)
	if runtime.GOOS == "windows" && filepath.Base(root) != "Octop Custom" && filepath.Base(root) != "OctopCustom" {
		return "", errors.New("unexpected Windows installation")
	}
	return root, nil
}

func Executable(root, platform string) string {
	if strings.HasPrefix(platform, "darwin-") {
		return filepath.Join(root, "Contents", "MacOS", "OctopCustom")
	}
	return filepath.Join(root, "OctopCustom.exe")
}
func Helper(root, platform string) string {
	if strings.HasPrefix(platform, "darwin-") {
		return filepath.Join(root, "Contents", "Helpers", "client-updater")
	}
	return filepath.Join(root, "client-updater.exe")
}
func BuildFile(root, platform string) string {
	if strings.HasPrefix(platform, "darwin-") {
		return filepath.Join(root, "Contents", "Resources", "client-update-build.json")
	}
	return filepath.Join(root, "client-update-build.json")
}

func LoadBuild(root, platform string) (Build, error) {
	var build Build
	data, err := os.ReadFile(BuildFile(root, platform))
	if err != nil {
		return build, err
	}
	if err = decodeStrict(data, &build); err != nil {
		return build, err
	}
	if build.Product != Product || build.Protocol != Protocol || !versionPattern.MatchString(build.Version) {
		return build, fmt.Errorf("invalid desktop build metadata")
	}
	return build, nil
}
