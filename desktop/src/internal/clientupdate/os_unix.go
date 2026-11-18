//go:build !windows

package clientupdate

import (
	"errors"
	"os"
	"syscall"
)

func replaceFile(source, target string) error { return os.Rename(source, target) }
func ProcessAlive(pid int) bool {
	return pid > 0 && (syscall.Kill(pid, 0) == nil || errors.Is(syscall.Kill(pid, 0), syscall.EPERM))
}
func TerminateProcess(pid int) error {
	if pid <= 0 {
		return nil
	}
	return syscall.Kill(pid, syscall.SIGTERM)
}
func FreeSpace(path string) (uint64, error) {
	var info syscall.Statfs_t
	err := syscall.Statfs(path, &info)
	return info.Bavail * uint64(info.Bsize), err
}
