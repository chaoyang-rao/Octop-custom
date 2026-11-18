package clientupdate

import (
	"archive/zip"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

func inside(root, path string) bool {
	rel, err := filepath.Rel(root, path)
	return err == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)) && !filepath.IsAbs(rel)
}

func CopyTree(source, destination string, skip func(string) bool) error {
	return filepath.WalkDir(source, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		rel, err := filepath.Rel(source, path)
		if err != nil {
			return err
		}
		if rel != "." && skip != nil && skip(rel) {
			if entry.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		target := filepath.Join(destination, rel)
		info, err := os.Lstat(path)
		if err != nil {
			return err
		}
		if info.Mode()&os.ModeSymlink != 0 {
			link, err := os.Readlink(path)
			if err != nil {
				return err
			}
			if err := os.MkdirAll(filepath.Dir(target), 0700); err != nil {
				return err
			}
			return os.Symlink(link, target)
		}
		if info.IsDir() {
			return os.MkdirAll(target, info.Mode().Perm())
		}
		if !info.Mode().IsRegular() {
			return fmt.Errorf("unsupported file in backup")
		}
		if err := os.MkdirAll(filepath.Dir(target), 0700); err != nil {
			return err
		}
		input, err := os.Open(path)
		if err != nil {
			return err
		}
		defer input.Close()
		output, err := os.OpenFile(target, os.O_CREATE|os.O_EXCL|os.O_WRONLY, info.Mode().Perm())
		if err != nil {
			return err
		}
		_, err = io.Copy(output, input)
		closeErr := output.Close()
		if err != nil {
			return err
		}
		return closeErr
	})
}

func DataExcluded(relative string) bool {
	name := strings.Split(filepath.ToSlash(relative), "/")[0]
	return name == "client-updates" || name == "backups"
}

func RestoreData(snapshot, home string) error {
	entries, err := os.ReadDir(home)
	if err != nil {
		return err
	}
	for _, entry := range entries {
		if !DataExcluded(entry.Name()) {
			if err := os.RemoveAll(filepath.Join(home, entry.Name())); err != nil {
				return err
			}
		}
	}
	return CopyTree(snapshot, home, DataExcluded)
}

func ExtractPackage(archivePath, destination, platform string) error {
	archive, err := zip.OpenReader(archivePath)
	if err != nil {
		return err
	}
	defer archive.Close()
	if len(archive.File) > 30000 {
		return errors.New("too many package entries")
	}
	prefix := "OctopCustom/"
	if strings.HasPrefix(platform, "darwin-") {
		prefix = "OctopCustom.app/"
	}
	seen := map[string]bool{}
	links := map[string]string{}
	var total uint64
	for _, file := range archive.File {
		if !strings.HasPrefix(file.Name, prefix) || strings.ContainsAny(file.Name, "\\:\x00") {
			return errors.New("invalid package path")
		}
		relative := strings.TrimPrefix(file.Name, prefix)
		if relative == "" && file.FileInfo().IsDir() {
			continue
		}
		for _, component := range strings.Split(strings.TrimSuffix(relative, "/"), "/") {
			if component == "" || component == "." || component == ".." {
				return errors.New("non-canonical package path")
			}
			if strings.HasPrefix(platform, "windows-") {
				base := strings.ToUpper(strings.Split(component, ".")[0])
				if strings.TrimRight(component, " .") != component || base == "CON" || base == "PRN" || base == "AUX" || base == "NUL" || (len(base) == 4 && (strings.HasPrefix(base, "COM") || strings.HasPrefix(base, "LPT")) && base[3] >= '1' && base[3] <= '9') {
					return errors.New("reserved Windows package path")
				}
			}
		}
		target := filepath.Join(destination, filepath.FromSlash(relative))
		if !inside(destination, target) || relative == "" || seen[strings.ToLower(target)] {
			return errors.New("duplicate or escaped package path")
		}
		seen[strings.ToLower(target)] = true
		total += file.UncompressedSize64
		if total > 4<<30 {
			return errors.New("expanded update is too large")
		}
		if file.FileInfo().IsDir() {
			if err := os.MkdirAll(target, 0755); err != nil {
				return err
			}
			continue
		}
		if err := os.MkdirAll(filepath.Dir(target), 0755); err != nil {
			return err
		}
		input, err := file.Open()
		if err != nil {
			return err
		}
		if file.Mode()&os.ModeSymlink != 0 {
			data, readErr := io.ReadAll(io.LimitReader(input, 4097))
			input.Close()
			if readErr != nil || len(data) > 4096 || !strings.HasPrefix(platform, "darwin-") {
				return errors.New("invalid package link")
			}
			link := string(data)
			if filepath.IsAbs(link) || strings.ContainsAny(link, "\\:\x00") || !inside(destination, filepath.Clean(filepath.Join(filepath.Dir(target), link))) {
				return errors.New("escaped package link")
			}
			links[target] = link
			continue
		}
		if !file.Mode().IsRegular() {
			input.Close()
			return errors.New("unsupported package entry")
		}
		mode := file.Mode().Perm()
		if mode == 0 {
			mode = 0644
		}
		output, err := os.OpenFile(target, os.O_CREATE|os.O_EXCL|os.O_WRONLY, mode)
		if err != nil {
			input.Close()
			return err
		}
		_, copyErr := io.Copy(output, io.LimitReader(input, int64(file.UncompressedSize64)+1))
		input.Close()
		closeErr := output.Close()
		if copyErr != nil {
			return copyErr
		}
		if closeErr != nil {
			return closeErr
		}
	}
	for path, link := range links {
		for other := range seen {
			if strings.HasPrefix(other, strings.ToLower(path)+string(filepath.Separator)) {
				return errors.New("package content traverses a link")
			}
		}
		if err := os.Symlink(link, path); err != nil {
			return err
		}
	}
	for path := range links {
		resolved, err := filepath.EvalSymlinks(path)
		if err != nil || !inside(destination, resolved) {
			return errors.New("invalid resolved package link")
		}
	}
	for _, required := range []string{Executable(destination, platform), Helper(destination, platform), BuildFile(destination, platform)} {
		info, err := os.Stat(required)
		if err != nil || !info.Mode().IsRegular() {
			return errors.New("incomplete application update")
		}
	}
	return nil
}

func TreeSize(root string, skip func(string) bool) (uint64, error) {
	var total uint64
	err := filepath.WalkDir(root, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, e := filepath.Rel(root, path)
		if e != nil {
			return e
		}
		if rel != "." && skip != nil && skip(rel) {
			if entry.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		info, e := os.Lstat(path)
		if e != nil {
			return e
		}
		if info.Mode().IsRegular() {
			total += uint64(info.Size())
		}
		return nil
	})
	return total, err
}
