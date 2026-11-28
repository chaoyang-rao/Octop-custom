package clientupdate

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestCandidateHealthAcceptsNativeDashboardRoot(t *testing.T) {
	for _, product := range []string{Product, CompanionProduct} {
		t.Run(product, func(t *testing.T) {
			version := "1.0.3b3.post2026112809"
			endpoint := "/api/health"
			if product == CompanionProduct {
				version = "0.10.10"
				endpoint += "/companion"
			}
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path != endpoint {
					http.NotFound(w, r)
					return
				}
				_ = json.NewEncoder(w).Encode(map[string]any{
					"ok": true, "custom_release": version, "client_update_pending": true,
					"companion": true, "companion_version": version,
				})
			}))
			defer server.Close()
			for _, test := range []struct {
				name, suffix string
				want         bool
			}{
				{"canonical", "", true},
				{"native dashboard trailing slash", "/", true},
				{"unrelated path", "/other", false},
				{"query", "?other=1", false},
			} {
				t.Run(test.name, func(t *testing.T) {
					job := &Job{CandidateBase: server.URL + test.suffix, TargetVersion: version}
					if got := candidateHealthyForProduct(job, product); got != test.want {
						t.Fatalf("candidate health=%v, want %v for %q", got, test.want, job.CandidateBase)
					}
				})
			}
		})
	}
}
