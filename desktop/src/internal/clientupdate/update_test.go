package clientupdate

import (
	"archive/zip"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func signedFixture(t *testing.T) (Envelope, []byte) {
	t.Helper()
	public, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(public)
	id := hex.EncodeToString(digest[:])[:16]
	release := Release{Schema: 1, Protocol: 1, Authority: "https://company.example", Revision: 2, Version: "1.0.3b3.post2026111802", Tag: "custom-1.0.3b3-20261118.2", SourceCommit: strings.Repeat("a", 40), Enabled: true}
	for _, platform := range []string{"windows-amd64", "darwin-arm64", "darwin-amd64"} {
		name := "OctopCustom-update-" + platform + "-" + release.Version + ".zip"
		release.Packages = append(release.Packages, Package{Platform: platform, Filename: name, URL: "https://github.com/" + Repository + "/releases/download/" + release.Tag + "/" + name, SHA256: strings.Repeat("b", 64), Size: 10})
	}
	data, _ := json.Marshal(release)
	pins, _ := json.Marshal(map[string]any{"schema_version": 1, "authorities": map[string]any{release.Authority: map[string]string{id: base64.StdEncoding.EncodeToString(public)}}})
	return Envelope{KeyID: id, Payload: base64.StdEncoding.EncodeToString(data), Signature: base64.StdEncoding.EncodeToString(ed25519.Sign(private, data))}, pins
}

func writeTestFile(t *testing.T, path, value string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(value), 0600); err != nil {
		t.Fatal(err)
	}
}

func TestSignatureAuthorityAndTamper(t *testing.T) {
	envelope, pins := signedFixture(t)
	if _, err := VerifyWithTrust(envelope, "https://company.example", pins); err != nil {
		t.Fatal(err)
	}
	if _, err := VerifyWithTrust(envelope, "https://other.example", pins); err == nil {
		t.Fatal("accepted another authority")
	}
	data, _ := base64.StdEncoding.DecodeString(envelope.Payload)
	envelope.Payload = base64.StdEncoding.EncodeToString(append(data, ' '))
	if _, err := VerifyWithTrust(envelope, "https://company.example", pins); err == nil {
		t.Fatal("accepted modified bytes")
	}
}

func TestApprovalExpiresBeforeAnyFileReplacement(t *testing.T) {
	if HostPlatform() != "darwin-arm64" && HostPlatform() != "darwin-amd64" && HostPlatform() != "windows-amd64" {
		t.Skip("shipped platforms only")
	}
	envelope, pins := signedFixture(t)
	previous := trustJSON
	trustJSON = pins
	t.Cleanup(func() { trustJSON = previous })
	job := &Job{Schema: 1, ID: strings.Repeat("1", 32), Owner: 1, Subject: strings.Repeat("a", 64), Platform: HostPlatform(), CurrentVersion: "1.0.3b3.post2026111801", TargetVersion: "1.0.3b3.post2026111802", Revision: 2, Phase: "applying", ApprovedAt: time.Now().Unix(), ExpiresAt: time.Now().Add(time.Minute).Unix(), Envelope: envelope}
	build := Build{Version: job.CurrentVersion, Authority: "https://company.example"}
	if _, err := ValidateJob(job, build, time.Now()); err != nil {
		t.Fatal(err)
	}
	job.ExpiresAt = time.Now().Add(-time.Minute).Unix()
	if _, err := ValidateJob(job, build, time.Now()); err == nil {
		t.Fatal("accepted expired local consent")
	}
	job.ExpiresAt = time.Now().Add(time.Minute).Unix()
	job.CurrentVersion = "1.0.3b3.post2026111803"
	if _, err := ValidateJob(job, build, time.Now()); err == nil {
		t.Fatal("accepted another installed version")
	}
}

func TestJournalRejectsTraversalAndSymlink(t *testing.T) {
	home := t.TempDir()
	if _, err := ReadJob(home, "../other"); err == nil {
		t.Fatal("accepted escaped job id")
	}
	outside := t.TempDir()
	if err := os.Symlink(outside, filepath.Join(home, "client-updates")); err != nil {
		t.Skip("symlinks unavailable")
	}
	if _, err := JobDir(home, strings.Repeat("a", 32)); err == nil {
		t.Fatal("accepted linked journal")
	}
}

func makeZIP(t *testing.T, name string, mode os.FileMode, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "payload.zip")
	file, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	archive := zip.NewWriter(file)
	header := &zip.FileHeader{Name: name}
	header.SetMode(mode)
	entry, err := archive.CreateHeader(header)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = entry.Write([]byte(body)); err != nil {
		t.Fatal(err)
	}
	if err = archive.Close(); err != nil {
		t.Fatal(err)
	}
	file.Close()
	return path
}

func TestUnsafeArchivesCannotEscapeStage(t *testing.T) {
	for _, name := range []string{"OctopCustom/../outside", "OctopCustom/a/../../outside", "OctopCustom/C:/outside", "OctopCustom/NUL.txt", "OctopCustom/a. /file", "OctopCustom/a/./b"} {
		t.Run(name, func(t *testing.T) {
			destination := filepath.Join(t.TempDir(), "stage")
			if err := ExtractPackage(makeZIP(t, name, 0600, "bad"), destination, "windows-amd64"); err == nil {
				t.Fatal("accepted unsafe archive")
			}
		})
	}
	if err := ExtractPackage(makeZIP(t, "OctopCustom.app/link", os.ModeSymlink|0777, "../../outside"), filepath.Join(t.TempDir(), "stage"), "darwin-arm64"); err == nil {
		t.Fatal("accepted escaping symlink")
	}
}

func TestDataRollbackPreservesPrivateStateAndExistingBackups(t *testing.T) {
	home := t.TempDir()
	snapshot := filepath.Join(t.TempDir(), "snapshot")
	writeTestFile(t, filepath.Join(home, "octop.db"), "old chats and memory")
	writeTestFile(t, filepath.Join(home, "config.json"), "personal MCP authorization")
	writeTestFile(t, filepath.Join(home, "backups", "existing.zip"), "existing backup")
	writeTestFile(t, filepath.Join(home, "client-updates", "journal"), "update state")
	if err := CopyTree(home, snapshot, DataExcluded); err != nil {
		t.Fatal(err)
	}
	writeTestFile(t, filepath.Join(home, "octop.db"), "new schema")
	writeTestFile(t, filepath.Join(home, "unexpected-new-file"), "new")
	if err := RestoreData(snapshot, home); err != nil {
		t.Fatal(err)
	}
	for name, want := range map[string]string{"octop.db": "old chats and memory", "config.json": "personal MCP authorization", "backups/existing.zip": "existing backup", "client-updates/journal": "update state"} {
		got, err := os.ReadFile(filepath.Join(home, filepath.FromSlash(name)))
		if err != nil || string(got) != want {
			t.Fatalf("lost %s", name)
		}
	}
	if _, err := os.Stat(filepath.Join(home, "unexpected-new-file")); !os.IsNotExist(err) {
		t.Fatal("retained uncommitted schema file")
	}
}

func TestRollbackRestoresProgramAndRefusesAcceptedUpdate(t *testing.T) {
	home := t.TempDir()
	app := filepath.Join(t.TempDir(), "OctopCustom")
	job := &Job{Schema: 1, ID: strings.Repeat("2", 32), DataRoot: home, AppRoot: app, Platform: "windows-amd64", Phase: "starting", BackupReady: true, ProgramMoved: true}
	directory, _ := JobDir(home, job.ID)
	for _, name := range []string{"client-updater.exe", "client-update-build.json", "OctopCustom.exe"} {
		writeTestFile(t, filepath.Join(app, name), "new")
		writeTestFile(t, filepath.Join(directory, "backup/program", name), "previous")
	}
	writeTestFile(t, filepath.Join(home, "octop.db"), "new database")
	writeTestFile(t, filepath.Join(directory, "backup/data/octop.db"), "previous database")
	if err := SaveJob(job); err != nil {
		t.Fatal(err)
	}
	launches := 0
	installer := Installer{Job: job, Launch: func(_ string, _ []string, _ []string) (int, error) { launches++; return 0, nil }}
	if err := installer.Rollback(context.Background()); err != nil {
		t.Fatal(err)
	}
	got, _ := os.ReadFile(filepath.Join(app, "OctopCustom.exe"))
	if string(got) != "previous" || launches != 1 {
		t.Fatal("previous program was not relaunched")
	}
	got, _ = os.ReadFile(filepath.Join(home, "octop.db"))
	if string(got) != "previous database" {
		t.Fatal("database was not restored")
	}
	job.Phase = "accepted"
	SaveJob(job)
	writeTestFile(t, filepath.Join(home, "octop.db"), "new user work")
	if err := installer.Rollback(context.Background()); err == nil {
		t.Fatal("accepted update rolled back user work")
	}
	got, _ = os.ReadFile(filepath.Join(home, "octop.db"))
	if string(got) != "new user work" {
		t.Fatal("new user work was changed")
	}
}

func TestCandidateHealthRequiresExactVersionAndPendingGate(t *testing.T) {
	version := "1.0.3b3.post2026111802"
	pending := true
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]any{"ok": true, "custom_release": version, "client_update_pending": pending})
	}))
	defer server.Close()
	job := &Job{TargetVersion: version, CandidateBase: server.URL}
	if !candidateHealthy(job) {
		t.Fatal("valid pending candidate rejected")
	}
	pending = false
	if candidateHealthy(job) {
		t.Fatal("candidate can already accept user work")
	}
	pending = true
	version = "old"
	if candidateHealthy(job) {
		t.Fatal("accepted stale backend")
	}
}
