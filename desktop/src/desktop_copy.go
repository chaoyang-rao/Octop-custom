package main

import "fmt"

const (
	copyStatusConnecting       = "status.connecting"
	copyStatusCheckingRuntime  = "status.checking_runtime"
	copyStatusStartingService  = "status.starting_service"
	copyStatusReady            = "status.ready"
	copyStatusUsingRuntime     = "status.using_runtime"
	copyStatusBackupDatabase   = "status.backup_database"
	copyStatusInstallingUpdate = "status.installing_update"
	copyStatusUpdatingRuntime  = "status.updating_runtime"
	copyStatusFirstExtract     = "status.first_extract"
	copyStatusUsingExisting    = "status.using_existing"
	copyErrorBackupFailed      = "error.backup_failed"
	copyErrorUpgradeFailed     = "error.upgrade_failed"
	copyErrorRuntimeConflict   = "error.runtime_conflict"
	copyErrorRuntimeMode       = "error.runtime_mode"
	copyErrorNoFreePort        = "error.no_free_port"
	copyErrorCannotBind        = "error.cannot_bind"
	copyWait1Minute            = "wait.1_minute"
	copyWaitNMinutes           = "wait.n_minutes"
	copyWait1Second            = "wait.1_second"
	copyWaitNSeconds           = "wait.n_seconds"
	copyHealthNotReady5xx      = "health.not_ready_5xx"
	copyHealthNotReadyConnect  = "health.not_ready_connect"
	copyHealthNotReady         = "health.not_ready"
	copyTraySettings           = "tray.settings"
	copyTrayShowMain           = "tray.show_main"
	copyTrayQuit               = "tray.quit"
)

var desktopCopy = map[Locale]map[string]string{
	LocaleEN: {
		copyStatusConnecting:       "Connecting to Octop…",
		copyStatusCheckingRuntime:  "Checking the runtime…",
		copyStatusStartingService:  "Starting the Octop service…",
		copyStatusReady:            "Octop is ready",
		copyStatusUsingRuntime:     "Using the existing runtime…",
		copyStatusBackupDatabase:   "Desktop update %s found. Backing up the database…",
		copyStatusInstallingUpdate: "Installing the bundled desktop update…",
		copyStatusUpdatingRuntime:  "Updating the bundled runtime…",
		copyStatusFirstExtract:     "First launch: unpacking the bundled runtime…",
		copyStatusUsingExisting:    "Octop is already running. Opening it…",
		copyErrorBackupFailed:      "Database backup failed before upgrade; the current version was preserved",
		copyErrorUpgradeFailed:     "Desktop runtime upgrade failed; the current version was preserved",
		copyErrorRuntimeConflict:   "Another Octop backend has a different version or login configuration. Save your work, fully quit the old Octop from the system tray, then restart Octop Custom. Closing its window may only minimise it to the tray.",
		copyErrorRuntimeMode:       "The installed runtime is newer but uses a different login authority. Install the matching Octop Custom package; the current runtime and data were preserved.",
		copyErrorNoFreePort:        "No free port from %d to %d. Close the program using these ports and try again.",
		copyErrorCannotBind:        "Cannot listen on %s:%d (%s). Check bind_host in config.json.",
		copyWait1Minute:            "1 minute",
		copyWaitNMinutes:           "%d minutes",
		copyWait1Second:            "1 second",
		copyWaitNSeconds:           "%d seconds",
		copyHealthNotReady5xx:      "Octop did not become ready within %s (%s). The service responded but is not ready yet. Try again, or check the terminal logs.",
		copyHealthNotReadyConnect:  "Octop did not become ready within %s (%s). Could not connect — make sure Octop is running.",
		copyHealthNotReady:         "Octop did not become ready within %s (%s). Make sure Octop is running at this address, or check the terminal logs.",
		copyTraySettings:           "Settings",
		copyTrayShowMain:           "Show Octop",
		copyTrayQuit:               "Quit",
	},
	LocaleZH: {
		copyStatusConnecting:       "正在连接 Octop…",
		copyStatusCheckingRuntime:  "正在检查运行环境…",
		copyStatusStartingService:  "正在启动 Octop 服务…",
		copyStatusReady:            "Octop 已就绪",
		copyStatusUsingRuntime:     "正在使用已有运行环境…",
		copyStatusBackupDatabase:   "发现客户端新版 %s，正在备份数据库…",
		copyStatusInstallingUpdate: "正在安装客户端内置新版…",
		copyStatusUpdatingRuntime:  "正在更新内置运行环境…",
		copyStatusFirstExtract:     "首次启动，正在解压内置运行环境…",
		copyStatusUsingExisting:    "Octop 已在运行，正在打开…",
		copyErrorBackupFailed:      "升级前数据库备份失败，已保留当前版本",
		copyErrorUpgradeFailed:     "客户端运行环境升级失败，已保留当前版本",
		copyErrorRuntimeConflict:   "检测到版本或登录配置不兼容的 Octop 后台。请先保存任务，从系统托盘完全退出旧 Octop，再重新启动 Octop Custom。关闭窗口可能只是最小化到托盘。",
		copyErrorRuntimeMode:       "已有运行环境版本更高，但登录中心不同。请安装对应的 Octop Custom 安装包；已保留当前运行环境与数据。",
		copyErrorNoFreePort:        "从 %d 到 %d 没有空闲端口，请关闭占用这些端口的程序后再试。",
		copyErrorCannotBind:        "无法在 %s:%d 上监听（%s）。请检查 config.json 里的 bind_host。",
		copyWait1Minute:            "1 分钟",
		copyWaitNMinutes:           "%d 分钟",
		copyWait1Second:            "1 秒",
		copyWaitNSeconds:           "%d 秒",
		copyHealthNotReady5xx:      "Octop 服务未在%s内就绪（%s）。服务已响应但尚未就绪，请稍后再试，或查看终端日志。",
		copyHealthNotReadyConnect:  "Octop 服务未在%s内就绪（%s）。目前无法连接该地址，请确认 Octop 正在运行。",
		copyHealthNotReady:         "Octop 服务未在%s内就绪（%s）。请确认本机已启动 Octop，且地址、端口正确；也可查看终端日志。",
		copyTraySettings:           "设置",
		copyTrayShowMain:           "显示 Octop",
		copyTrayQuit:               "退出",
	},
}

func desktopText(locale Locale, key string, args ...any) string {
	msg := lookupDesktopCopy(locale, key)
	if len(args) == 0 {
		return msg
	}
	return fmt.Sprintf(msg, args...)
}

func lookupDesktopCopy(locale Locale, key string) string {
	if msgs := desktopCopy[locale]; msgs != nil {
		if msg, ok := msgs[key]; ok {
			return msg
		}
	}
	if msg, ok := desktopCopy[LocaleEN][key]; ok {
		return msg
	}
	return key
}
