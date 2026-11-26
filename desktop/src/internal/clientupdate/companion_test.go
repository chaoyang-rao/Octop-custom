package clientupdate

import (
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func signCompanionFixture(t *testing.T, release Release) (Envelope, []byte) {
	t.Helper()
	public, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(public)
	keyID := hex.EncodeToString(digest[:])[:16]
	data, err := json.Marshal(release)
	if err != nil {
		t.Fatal(err)
	}
	pins, _ := json.Marshal(map[string]any{"schema_version": 1, "authorities": map[string]any{release.Authority: map[string]string{keyID: base64.StdEncoding.EncodeToString(public)}}})
	return Envelope{KeyID: keyID, Payload: base64.StdEncoding.EncodeToString(data), Signature: base64.StdEncoding.EncodeToString(ed25519.Sign(private, data))}, pins
}
func companionFixture(t *testing.T) Release {
	t.Helper()
	release := Release{Product: CompanionProduct, Schema: 1, Protocol: 1, Authority: "https://company.example", Revision: 2, Version: "0.10.0", Tag: "custom-1.0.3b3-20261126.1", SourceCommit: strings.Repeat("b", 40), Enabled: true}
	for _, platform := range []string{"windows-amd64", "darwin-amd64", "darwin-arm64"} {
		name := "Dora-update-" + platform + "-" + release.Version + ".zip"
		release.Packages = append(release.Packages, Package{Platform: platform, Filename: name, URL: "https://github.com/" + Repository + "/releases/download/" + release.Tag + "/" + name, SHA256: strings.Repeat("a", 64), Size: 100})
	}
	return release
}
func TestCompanionCannotReplaceTheMainClient(t *testing.T) {
	if HostPlatform() != "windows-amd64" && HostPlatform() != "darwin-arm64" && HostPlatform() != "darwin-amd64" {
		t.Skip("shipped native platforms")
	}
	release := companionFixture(t)
	envelope, pins := signCompanionFixture(t, release)
	old := trustJSON
	trustJSON = pins
	t.Cleanup(func() { trustJSON = old })
	job := &Job{Product: CompanionProduct, Schema: 1, Owner: 1, Subject: strings.Repeat("a", 64), Platform: HostPlatform(), CurrentVersion: "0.9.0", TargetVersion: release.Version, Revision: release.Revision, Phase: "applying", ApprovedAt: time.Now().Unix(), ExpiresAt: time.Now().Add(time.Minute).Unix(), Envelope: envelope}
	build := Build{Product: CompanionProduct, Protocol: 1, Version: "0.9.0", Authority: release.Authority}
	if _, err := ValidateJob(job, build, time.Now()); err != nil {
		t.Fatal(err)
	}
	build.Product = Product
	if _, err := ValidateJob(job, build, time.Now()); err == nil {
		t.Fatal("companion accepted for main client")
	}
	build.Product = CompanionProduct
	build.Version = release.Version
	job.Phase = "starting"
	if err := ValidateCandidate(job, build); err != nil {
		t.Fatal(err)
	}
	job.Subject = "bad"
	if err := ValidateCandidate(job, build); err == nil {
		t.Fatal("invalid candidate identity accepted")
	}
}
