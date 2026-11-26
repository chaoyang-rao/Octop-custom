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
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// Exercise the real Mac directory exchange, signed bundle validation, snapshot
// and failure recovery without touching the installed application or user home.
func TestNativeInstallFailureRestoresPreviousProgramAndData(t *testing.T) {
	for _, product := range []string{Product, CompanionProduct} {
		t.Run(product, func(t *testing.T) { nativeInstallFailure(t, product) })
	}
}
func nativeInstallFailure(t *testing.T, product string) {
	home := t.TempDir()
	parent := t.TempDir()
	app := filepath.Join(parent, "OctopCustom.app")
	stageSource := filepath.Join(t.TempDir(), "OctopCustom.app")
	if product == CompanionProduct {
		app = filepath.Join(parent, "Dora.app")
		stageSource = filepath.Join(t.TempDir(), "Dora.app")
	}
	platform := HostPlatform()
	version := "1.0.3b3.post2026111802"
	previousVersion := "1.0.3b3.post2026111801"
	if product == CompanionProduct {
		version = "0.10.0"
		previousVersion = "0.9.0"
	}
	authority := "https://company.example"
	binary, err := os.ReadFile("/usr/bin/true")
	if err != nil {
		t.Fatal(err)
	}
	for _, root := range []string{app, stageSource} {
		for _, name := range []string{ExecutableForProduct(root, platform, product), HelperForProduct(root, platform, product)} {
			if err = os.MkdirAll(filepath.Dir(name), 0755); err != nil {
				t.Fatal(err)
			}
			if err = os.WriteFile(name, binary, 0755); err != nil {
				t.Fatal(err)
			}
		}
		data, _ := json.Marshal(Build{Product: product, Protocol: 1, Version: version, Authority: authority})
		writeTestFile(t, BuildFileForProduct(root, platform, product), string(data))
		binaryName := "OctopCustom"
		if product == CompanionProduct {
			binaryName = "OctopCompanion"
		}
		writeTestFile(t, filepath.Join(root, "Contents/Info.plist"), `<?xml version="1.0"?><plist version="1.0"><dict><key>CFBundleIdentifier</key><string>com.chaoyangrao.octopcustom</string><key>CFBundleExecutable</key><string>`+binaryName+`</string><key>CFBundlePackageType</key><string>APPL</string></dict></plist>`)
	}
	writeTestFile(t, filepath.Join(app, "Contents/Resources/previous-marker"), "previous")
	if out, err := exec.Command("/usr/bin/codesign", "--force", "--deep", "--sign", "-", stageSource).CombinedOutput(); err != nil {
		t.Fatalf("codesign: %v: %s", err, out)
	}
	id := strings.Repeat("3", 32)
	directory, _ := JobDir(home, id)
	os.MkdirAll(directory, 0700)
	payload := filepath.Join(directory, "payload.zip")
	file, err := os.Create(payload)
	if err != nil {
		t.Fatal(err)
	}
	archive := zip.NewWriter(file)
	err = filepath.WalkDir(stageSource, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			return nil
		}
		relative, _ := filepath.Rel(filepath.Dir(stageSource), path)
		info, _ := entry.Info()
		header, _ := zip.FileInfoHeader(info)
		header.Name = filepath.ToSlash(relative)
		writer, createErr := archive.CreateHeader(header)
		if createErr != nil {
			return createErr
		}
		data, readErr := os.ReadFile(path)
		if readErr != nil {
			return readErr
		}
		_, writeErr := writer.Write(data)
		return writeErr
	})
	if err != nil {
		t.Fatal(err)
	}
	archive.Close()
	file.Close()
	digest, size, err := HashFile(payload)
	if err != nil {
		t.Fatal(err)
	}
	envelope, _ := signedFixture(t)
	raw, _ := base64.StdEncoding.DecodeString(envelope.Payload)
	var release Release
	json.Unmarshal(raw, &release)
	if product == CompanionProduct {
		release.Product = product
		release.Version = version
		for index := range release.Packages {
			item := &release.Packages[index]
			item.Filename = "Dora-update-" + item.Platform + "-" + version + ".zip"
			item.URL = "https://github.com/" + Repository + "/releases/download/" + release.Tag + "/" + item.Filename
		}
	}
	for index := range release.Packages {
		if release.Packages[index].Platform == platform {
			release.Packages[index].SHA256 = digest
			release.Packages[index].Size = size
		}
	}
	public, private, _ := ed25519.GenerateKey(rand.Reader)
	keyHash := sha256.Sum256(public)
	keyID := hex.EncodeToString(keyHash[:])[:16]
	raw, _ = json.Marshal(release)
	envelope = Envelope{KeyID: keyID, Payload: base64.StdEncoding.EncodeToString(raw), Signature: base64.StdEncoding.EncodeToString(ed25519.Sign(private, raw))}
	pins, _ := json.Marshal(map[string]any{"schema_version": 1, "authorities": map[string]any{authority: map[string]string{keyID: base64.StdEncoding.EncodeToString(public)}}})
	previousTrust := trustJSON
	trustJSON = pins
	t.Cleanup(func() { trustJSON = previousTrust })
	writeTestFile(t, filepath.Join(home, "octop.db"), "original chats, memory and credentials")
	job := &Job{Schema: 1, ID: id, DataRoot: home, AppRoot: app, Platform: platform, Owner: 1, Subject: strings.Repeat("a", 64), CurrentVersion: previousVersion, TargetVersion: version, Revision: 2, Phase: "applying", ApprovedAt: time.Now().Unix(), ExpiresAt: time.Now().Add(time.Minute).Unix(), Envelope: envelope}
	if product == CompanionProduct {
		job.Product = product
	}
	SaveJob(job)
	installer := Installer{Job: job, Build: Build{Product: product, Version: job.CurrentVersion, Authority: authority}, Launch: func(string, []string, []string) (int, error) {
		return 0, errors.New("injected candidate launch failure")
	}}
	if err = installer.Install(context.Background()); err == nil {
		t.Fatal("candidate unexpectedly launched")
	}
	if !installer.Job.ProgramMoved || !installer.Job.BackupReady {
		t.Fatal("did not exercise real installation and snapshot")
	}
	writeTestFile(t, filepath.Join(home, "octop.db"), "candidate schema")
	installer.Launch = func(string, []string, []string) (int, error) { return 0, nil }
	if err = installer.Rollback(context.Background()); err != nil {
		t.Fatal(err)
	}
	marker, _ := os.ReadFile(filepath.Join(app, "Contents/Resources/previous-marker"))
	if string(marker) != "previous" {
		t.Fatal("previous signed application was not restored")
	}
	content, _ := os.ReadFile(filepath.Join(home, "octop.db"))
	if string(content) != "original chats, memory and credentials" {
		t.Fatal("private data snapshot was not restored")
	}
}
