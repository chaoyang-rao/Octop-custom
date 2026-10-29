package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadSettingsMigratesLegacyPreventSleepMac(t *testing.T) {
	temp := t.TempDir()
	t.Setenv("OCTOP_HOME", temp)
	if err := os.WriteFile(
		settingsPath(),
		[]byte(`{"preventSleepMac":true}`),
		0o644,
	); err != nil {
		t.Fatal(err)
	}

	if !loadSettings().PreventSleep {
		t.Fatal("legacy preventSleepMac should migrate to preventSleep")
	}
}

func TestCustomShellPathsPreserveOfficialRuntimeAndSharedDataHome(t *testing.T) {
	home := t.TempDir()
	t.Setenv("OCTOP_HOME", home)
	if got := octopHome(); got != home {
		t.Fatalf("shared data home = %q", got)
	}
	if got := portableDir(); got != filepath.Join(home, "custom-runtime", "portable") {
		t.Fatalf("custom portable path = %q", got)
	}
	if got := settingsPath(); got == filepath.Join(home, "desktop-settings.json") {
		t.Fatal("custom shell must not overwrite official preferences")
	}
	if got := desktopPortPath(); got == filepath.Join(home, "desktop-port") {
		t.Fatal("custom shell must not reuse the official port marker")
	}
}
