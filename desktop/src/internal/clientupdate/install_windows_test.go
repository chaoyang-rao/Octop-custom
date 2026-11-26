package clientupdate

import (
	"archive/zip"
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestWindowsCompanionFailureRestoresProgramAndPrivateData(t *testing.T) {
	home, app := t.TempDir(), filepath.Join(t.TempDir(), "Dora")
	id := strings.Repeat("9", 32)
	directory, _ := JobDir(home, id)
	os.MkdirAll(directory, 0700)
	writeTestFile(t, filepath.Join(app, "Dora.exe"), "previous executable")
	writeTestFile(t, filepath.Join(app, "resources/web/index.html"), "previous UI")
	writeTestFile(t, filepath.Join(app, "Uninstall.exe"), "retained uninstaller")
	writeTestFile(t, filepath.Join(home, "octop.db"), "original private chats")
	release := companionFixture(t)
	build := Build{Product: CompanionProduct, Protocol: 1, Version: "0.9.0", Authority: release.Authority}
	current, _ := json.Marshal(build)
	writeTestFile(t, BuildFileForProduct(app, HostPlatform(), CompanionProduct), string(current))
	candidate := build
	candidate.Version = release.Version
	metadata, _ := json.Marshal(candidate)
	file, err := os.Create(filepath.Join(directory, "payload.zip"))
	if err != nil {
		t.Fatal(err)
	}
	archive := zip.NewWriter(file)
	for name, data := range map[string]string{"Dora/Dora.exe": "candidate executable", "Dora/resources/client-updater.exe": "candidate helper", "Dora/resources/client-update-build.json": string(metadata), "Dora/resources/web/index.html": "candidate UI"} {
		writer, err := archive.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		writer.Write([]byte(data))
	}
	archive.Close()
	file.Close()
	digest, size, err := HashFile(filepath.Join(directory, "payload.zip"))
	if err != nil {
		t.Fatal(err)
	}
	for index := range release.Packages {
		if release.Packages[index].Platform == HostPlatform() {
			release.Packages[index].SHA256 = digest
			release.Packages[index].Size = size
		}
	}
	envelope, pins := signCompanionFixture(t, release)
	old := trustJSON
	trustJSON = pins
	t.Cleanup(func() { trustJSON = old })
	job := &Job{Product: CompanionProduct, Schema: 1, ID: id, DataRoot: home, AppRoot: app, Platform: HostPlatform(), Owner: 1, Subject: strings.Repeat("a", 64), CurrentVersion: build.Version, TargetVersion: release.Version, Revision: 2, Phase: "applying", ApprovedAt: time.Now().Unix(), ExpiresAt: time.Now().Add(time.Minute).Unix(), Envelope: envelope}
	SaveJob(job)
	installer := Installer{Job: job, Build: build, Launch: func(string, []string, []string) (int, error) {
		return 0, errors.New("injected candidate startup failure")
	}}
	if err = installer.Install(context.Background()); err == nil || !job.ProgramMoved || !job.BackupReady {
		t.Fatalf("did not exercise replacement: %v", err)
	}
	writeTestFile(t, filepath.Join(home, "octop.db"), "candidate schema")
	installer.Launch = func(string, []string, []string) (int, error) { return 0, nil }
	if err = installer.Rollback(context.Background()); err != nil {
		t.Fatal(err)
	}
	for name, want := range map[string]string{filepath.Join(app, "Dora.exe"): "previous executable", filepath.Join(app, "resources/web/index.html"): "previous UI", filepath.Join(app, "Uninstall.exe"): "retained uninstaller", filepath.Join(home, "octop.db"): "original private chats"} {
		value, err := os.ReadFile(name)
		if err != nil || string(value) != want {
			t.Fatalf("restore mismatch %s: %v", name, err)
		}
	}
}
