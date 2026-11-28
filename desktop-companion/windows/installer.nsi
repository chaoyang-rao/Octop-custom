Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!define VERSION "0.10.9"
Name "哆啦"
OutFile "..\build\windows\Dora-Windows-x64-${VERSION}-Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\OctopCompanion"
RequestExecutionLevel user
!define MUI_ICON "..\build\windows\dora.ico"
!define MUI_UNICON "..\build\windows\dora.ico"
!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\Dora.exe"
!define MUI_FINISHPAGE_RUN_TEXT "打开哆啦"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"
VIProductVersion "0.10.9.0"
VIAddVersionKey "ProductName" "哆啦"
VIAddVersionKey "FileVersion" "0.10.9"
VIAddVersionKey "FileDescription" "哆啦独立桌宠"
VIAddVersionKey "LegalCopyright" "Octop Custom contributors"
Section "哆啦" SEC_MAIN
  SetShellVarContext current
  RMDir /r "$INSTDIR.stage"
  SetOutPath "$INSTDIR.stage"
  File /r "..\build\windows\Dora\*.*"
  SetOutPath "$TEMP"
  IfFileExists "$INSTDIR\Dora.exe" 0 install_new
  ClearErrors
  Rename "$INSTDIR" "$INSTDIR.previous"
  IfErrors running install_new
running:
  RMDir /r "$INSTDIR.stage"
  MessageBox MB_ICONEXCLAMATION|MB_OK "请先从系统托盘退出哆啦，再重新运行安装程序。"
  Abort
install_new:
  ClearErrors
  Rename "$INSTDIR.stage" "$INSTDIR"
  IfErrors rollback complete
rollback:
  Rename "$INSTDIR.previous" "$INSTDIR"
  Abort "安装未完成，已保留原程序与聊天数据。"
complete:
  SetOutPath "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\哆啦"
  CreateShortcut "$SMPROGRAMS\哆啦\哆啦.lnk" "$INSTDIR\Dora.exe"
  CreateShortcut "$DESKTOP\哆啦.lnk" "$INSTDIR\Dora.exe"
  WriteRegStr HKCU "Software\Classes\octop-companion" "" "URL:Octop Companion"
  WriteRegStr HKCU "Software\Classes\octop-companion" "URL Protocol" ""
  WriteRegStr HKCU "Software\Classes\octop-companion\shell\open\command" "" '"$INSTDIR\Dora.exe" "%1"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\OctopCompanion" "DisplayName" "哆啦"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\OctopCompanion" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\OctopCompanion" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  RMDir /r "$INSTDIR.previous"
SectionEnd
Section "Uninstall"
  SetOutPath "$TEMP"
  Delete "$DESKTOP\哆啦.lnk"
  RMDir /r "$SMPROGRAMS\哆啦"
  DeleteRegKey HKCU "Software\Classes\octop-companion"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\OctopCompanion"
  RMDir /r "$INSTDIR"
  ; App-owned chats, login profile and artwork stay under LocalAppData\OctopCompanion.
SectionEnd
