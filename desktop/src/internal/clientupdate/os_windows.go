package clientupdate

import (
	"os/exec"
	"strconv"

	"golang.org/x/sys/windows"
)

func replaceFile(source, target string) error {
	a, err := windows.UTF16PtrFromString(source)
	if err != nil {
		return err
	}
	b, err := windows.UTF16PtrFromString(target)
	if err != nil {
		return err
	}
	return windows.MoveFileEx(a, b, windows.MOVEFILE_REPLACE_EXISTING|windows.MOVEFILE_WRITE_THROUGH)
}
func ProcessAlive(pid int) bool {
	if pid <= 0 {
		return false
	}
	handle, err := windows.OpenProcess(windows.PROCESS_QUERY_LIMITED_INFORMATION, false, uint32(pid))
	if err != nil {
		return false
	}
	defer windows.CloseHandle(handle)
	var code uint32
	if windows.GetExitCodeProcess(handle, &code) != nil {
		return false
	}
	return code == 259
}
func TerminateProcess(pid int) error {
	if pid <= 0 {
		return nil
	}
	return exec.Command("taskkill", "/PID", strconv.Itoa(pid), "/T", "/F").Run()
}
func FreeSpace(path string) (uint64, error) {
	value, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return 0, err
	}
	var available, total, free uint64
	err = windows.GetDiskFreeSpaceEx(value, &available, &total, &free)
	return available, err
}
