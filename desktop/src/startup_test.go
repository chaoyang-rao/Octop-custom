package main

import (
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const enterpriseTestOrigin = "https://login.example.test"

func TestStartupRejectsIncompatibleBackendBeforeChangingRuntime(t *testing.T) {
	for _, test := range []struct {
		name, version, authority, setup string
	}{
		{"old personal", "1.0.3b3.post20261106", "", ""},
		{"same version personal", "1.0.3b3.post2026110801", "", ""},
		{"different company", "1.0.3b3.post2026110801", "https://other.example.test", ""},
		{"official", "", "", ""},
		{"unreadable login configuration", "1.0.3b3.post2026110801", "", "invalid JSON"},
	} {
		for _, remembered := range []bool{false, true} {
			t.Run(fmt.Sprintf("%s/remembered=%v", test.name, remembered), func(t *testing.T) {
				home := t.TempDir()
				t.Setenv("OCTOP_HOME", home)
				t.Setenv("OCTOP_BIND_HOST", "127.0.0.1")
				bundle := filepath.Join(t.TempDir(), "enterprise.zip")
				writeTestGreenZip(t, bundle, "1.0.3b3.post2026110801", enterpriseTestOrigin)
				t.Setenv("OCTOP_DESKTOP_PORTABLE_ZIP", bundle)
				old := filepath.Join(t.TempDir(), "old.zip")
				writeTestGreenZip(t, old, "1.0.3b3.post20261106")
				if err := unzipGreen(old, portableDir()); err != nil {
					t.Fatal(err)
				}
				database := filepath.Join(home, "octop.db")
				if err := os.WriteFile(database, []byte("existing account and chats"), 0o600); err != nil {
					t.Fatal(err)
				}
				srv := httptest.NewServer(startupTestHandler(test.version, test.authority, test.setup))
				defer srv.Close()
				port := srv.Listener.Addr().(*net.TCPAddr).Port
				preferred := port
				if remembered {
					preferred = 1
					if err := writeDesktopPort(port); err != nil {
						t.Fatal(err)
					}
				}
				t.Setenv("OCTOP_PORT", fmt.Sprint(preferred))
				var statuses []string
				url, err := prepareDesktopRuntime(LocaleZH, func(s string) { statuses = append(statuses, s) })
				if url != "" || err == nil || !strings.Contains(err.Error(), "系统托盘完全退出") {
					t.Fatalf("url=%q err=%v", url, err)
				}
				if len(statuses) != 0 || portableVersion(portableDir()) != "1.0.3b3.post20261106" {
					t.Fatalf("running runtime was changed: statuses=%v", statuses)
				}
				if data, err := os.ReadFile(database); err != nil || string(data) != "existing account and chats" {
					t.Fatalf("database changed: %q %v", data, err)
				}
				if !octopAlreadyRunning(srv.URL) {
					t.Fatal("the existing backend must stay running")
				}
				if remembered {
					if actual, ok := readDesktopPort(); !ok || actual != port {
						t.Fatal("the other backend's port marker was changed")
					}
				}
			})
		}
	}
}

func TestStartupReusesCompatibleCompanyBackend(t *testing.T) {
	for _, version := range []string{"1.0.3b3.post2026110801", "1.0.3b3.post2026110901"} {
		t.Run(version, func(t *testing.T) {
			t.Setenv("OCTOP_HOME", t.TempDir())
			t.Setenv("OCTOP_BIND_HOST", "127.0.0.1")
			bundle := filepath.Join(t.TempDir(), "enterprise.zip")
			writeTestGreenZip(t, bundle, "1.0.3b3.post2026110801", enterpriseTestOrigin)
			t.Setenv("OCTOP_DESKTOP_PORTABLE_ZIP", bundle)
			srv := httptest.NewServer(startupTestHandler(version, enterpriseTestOrigin+"/", ""))
			defer srv.Close()
			t.Setenv("OCTOP_PORT", fmt.Sprint(srv.Listener.Addr().(*net.TCPAddr).Port))
			url, err := prepareDesktopRuntime(LocaleEN, func(string) { t.Fatal("reusing a backend must not extract files") })
			if err != nil || url != srv.URL+"/" {
				t.Fatalf("url=%q err=%v", url, err)
			}
		})
	}
}

func TestPortableReplacesPersonalRuntimeWithCompanyPresetAtSameVersion(t *testing.T) {
	t.Setenv("OCTOP_HOME", t.TempDir())
	personal := filepath.Join(t.TempDir(), "personal.zip")
	writeTestGreenZip(t, personal, "1.0.3b3.post2026110801")
	if err := unzipGreen(personal, portableDir()); err != nil {
		t.Fatal(err)
	}
	company := filepath.Join(t.TempDir(), "company.zip")
	writeTestGreenZip(t, company, "1.0.3b3.post2026110801", enterpriseTestOrigin)
	t.Setenv("OCTOP_DESKTOP_PORTABLE_ZIP", company)
	if err := ensurePortable(LocaleZH, func(string) {}); err != nil {
		t.Fatal(err)
	}
	identity, err := portableIdentity(portableDir())
	if err != nil || identity.Authority != enterpriseTestOrigin {
		t.Fatalf("identity=%+v err=%v", identity, err)
	}
}

func TestPortableDoesNotDowngradeNewerDifferentCompanyRuntime(t *testing.T) {
	t.Setenv("OCTOP_HOME", t.TempDir())
	current := filepath.Join(t.TempDir(), "current.zip")
	writeTestGreenZip(t, current, "1.0.3b3.post2026110901", "https://other.example.test")
	if err := unzipGreen(current, portableDir()); err != nil {
		t.Fatal(err)
	}
	bundle := filepath.Join(t.TempDir(), "bundled.zip")
	writeTestGreenZip(t, bundle, "1.0.3b3.post2026110801", enterpriseTestOrigin)
	t.Setenv("OCTOP_DESKTOP_PORTABLE_ZIP", bundle)
	if err := ensurePortable(LocaleZH, func(string) {}); err == nil {
		t.Fatal("a different company preset must require an explicit matching package")
	}
	identity, err := portableIdentity(portableDir())
	if err != nil || identity.Version != "1.0.3b3.post2026110901" || identity.Authority != "https://other.example.test" {
		t.Fatalf("existing runtime changed: %+v %v", identity, err)
	}
}

func startupTestHandler(version, authority, setup string) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/api/health":
			_ = json.NewEncoder(w).Encode(map[string]any{"ok": true, "users_loaded": 1, "agents_running": 1, "custom_release": version})
		case "/api/setup/status":
			if setup != "" {
				_, _ = w.Write([]byte(setup))
				return
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"enterprise_login": authority != "", "enterprise_authority_url": authority, "database_bound": true})
		default:
			http.NotFound(w, r)
		}
	})
}
