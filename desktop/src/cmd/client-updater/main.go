// The signed, standalone helper survives replacement of the GUI application.
package main

import (
	"context"
	"flag"
	"os"
	"path/filepath"
	"time"

	"octop.desktop/internal/clientupdate"
)

func main() {
	home := flag.String("home", "", "local Octop home")
	identifier := flag.String("job", "", "approved local update id")
	recover := flag.Bool("recover", false, "recover interrupted installation")
	waitPID := flag.Int("wait-pid", 0, "GUI process that must exit before recovery")
	product := flag.String("product", clientupdate.Product, "fixed local application product")
	validate := flag.Bool("validate", false, "validate a native handoff without installing")
	candidate := flag.Bool("candidate", false, "validate candidate startup without installing")
	flag.Parse()
	if *home == "" || !filepath.IsAbs(*home) {
		os.Exit(2)
	}
	job, err := clientupdate.ReadJob(filepath.Clean(*home), *identifier)
	if err != nil {
		os.Exit(2)
	}
	build, err := clientupdate.LoadBuildForProduct(job.AppRoot, job.Platform, *product)
	if err != nil {
		_ = clientupdate.Fail(job, "CLIENT_UPDATE_INTEGRITY")
		os.Exit(2)
	}
	if *validate {
		if _, err := clientupdate.ValidateJob(job, build, time.Now()); err != nil {
			os.Exit(2)
		}
		return
	}
	if *candidate {
		if clientupdate.ValidateCandidate(job, build) != nil {
			os.Exit(2)
		}
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Minute)
	defer cancel()
	installer := &clientupdate.Installer{Job: job, Build: build}
	if *recover {
		release, verifyErr := clientupdate.Verify(job.Envelope, build.Authority)
		if verifyErr != nil || release.Version != job.TargetVersion || job.Phase == "accepted" || job.Phase == "rolled_back" || !job.BackupReady {
			os.Exit(2)
		}
	}
	if *recover && *waitPID > 0 {
		deadline := time.Now().Add(30 * time.Second)
		for clientupdate.ProcessAlive(*waitPID) && time.Now().Before(deadline) {
			time.Sleep(100 * time.Millisecond)
		}
		if clientupdate.ProcessAlive(*waitPID) {
			os.Exit(2)
		}
	}
	if !*recover {
		err = installer.Install(ctx)
	}
	if err != nil || *recover {
		job = installer.Job
		if !clientupdate.ProcessAlive(job.OldPID) || job.ProgramMoved {
			recovery, recoveryCancel := context.WithTimeout(context.Background(), 2*time.Minute)
			defer recoveryCancel()
			if installer.Rollback(recovery) != nil {
				_ = clientupdate.Fail(job, "CLIENT_UPDATE_RECOVERY_REQUIRED")
			}
		} else {
			_ = clientupdate.Fail(job, "CLIENT_UPDATE_FAILED")
		}
		os.Exit(1)
	}
}
