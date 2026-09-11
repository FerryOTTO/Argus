; Clawguard 自定义 NSIS 逻辑（中文注释）。
; 做一件事：卸载时多一个“清理残留”选项页，可勾选
;   1) Python 依赖包（pip 卸载装机时装的包）
;   2) OpenClaw 全局包（npm 卸载全局 openclaw）
;   3) 用户数据（本机配置、日志、向导标记）
; 默认三个都不勾，只删程序本身。Python / Node.js 本体永远不动；
; 工作台依赖装在安装目录里，已随程序一起删除。
; 注意：安装包本来就不带任何令牌，这里不需要处理令牌。

!include "nsDialogs.nsh"
!include "LogicLib.nsh"

!macro customUninstallPage
  UninstPage custom un.OptsCreate un.OptsLeave
!macroend

!ifdef BUILD_UNINSTALLER

Var UninstallChkPyDeps
Var UninstallChkOpenClaw
Var UninstallChkAppData
Var UninstallOptPyDeps
Var UninstallOptOpenClaw
Var UninstallOptAppData
Var UninstallPythonCmd
Var UninstallNpmCmd

Function un.OptsCreate
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}

  ${NSD_CreateLabel} 0 0 290u 18u "程序文件已删除。勾选要一并清理的残留（默认都不勾，只删程序本身）："
  Pop $0

  ${NSD_CreateCheckbox} 10u 22u 280u 12u "Python 依赖包（pip 卸载装机时装的十几个包）"
  Pop $UninstallChkPyDeps
  ${If} $UninstallOptPyDeps == "1"
    ${NSD_Check} $UninstallChkPyDeps
  ${EndIf}

  ${NSD_CreateLabel} 20u 36u 270u 20u "注意：如果本机其他 Python 软件也在用这些包，卸掉可能影响它们。"
  Pop $0

  ${NSD_CreateCheckbox} 10u 60u 280u 12u "OpenClaw 全局包（npm 卸载全局 openclaw）"
  Pop $UninstallChkOpenClaw
  ${If} $UninstallOptOpenClaw == "1"
    ${NSD_Check} $UninstallChkOpenClaw
  ${EndIf}

  ${NSD_CreateCheckbox} 10u 76u 280u 12u "用户数据（本机配置、日志、向导标记，删后下次打开会重新走一遍向导）"
  Pop $UninstallChkAppData
  ${If} $UninstallOptAppData == "1"
    ${NSD_Check} $UninstallChkAppData
  ${EndIf}

  ${NSD_CreateLabel} 20u 92u 270u 24u "说明：Python / Node.js 本体不会动。工作台依赖在安装目录里，已随程序一起删除。"
  Pop $0

  nsDialogs::Show
FunctionEnd

Function un.OptsLeave
  ${NSD_GetState} $UninstallChkPyDeps $UninstallOptPyDeps
  ${NSD_GetState} $UninstallChkOpenClaw $UninstallOptOpenClaw
  ${NSD_GetState} $UninstallChkAppData $UninstallOptAppData
FunctionEnd

Function un.DetectPyNpm
  StrCpy $UninstallPythonCmd ""
  nsExec::ExecToStack 'python -m pip --version'
  Pop $0
  Pop $1
  ${If} $1 == "0"
    StrCpy $UninstallPythonCmd "python"
  ${Else}
    nsExec::ExecToStack 'py -3 -m pip --version'
    Pop $0
    Pop $1
    ${If} $1 == "0"
      StrCpy $UninstallPythonCmd "py -3"
    ${EndIf}
  ${EndIf}

  StrCpy $UninstallNpmCmd ""
  nsExec::ExecToStack 'npm --version'
  Pop $0
  Pop $1
  ${If} $1 == "0"
    StrCpy $UninstallNpmCmd "npm"
  ${EndIf}
FunctionEnd

Function un.RemovePyDeps
  DetailPrint "正在卸载 Python 依赖包，请稍候..."
  nsExec::ExecToStack '$UninstallPythonCmd -m pip uninstall -y fastapi uvicorn pydantic PyYAML httpx networkx numpy aiosqlite APScheduler bcrypt PyJWT websockets python-docx PyMuPDF openpyxl Pillow joblib scikit-learn'
  Pop $0
  Pop $1
  DetailPrint "pip 退出码：$1"
  ${If} $1 != "0"
    DetailPrint $0
    MessageBox MB_OK|MB_ICONEXCLAMATION "Python 依赖包没有完全卸掉，可看卸载日志详情，或手动运行 pip uninstall 卸载。"
  ${Else}
    DetailPrint "Python 依赖包已卸载。"
  ${EndIf}
FunctionEnd

Function un.RemoveOpenClaw
  DetailPrint "正在卸载 OpenClaw 全局包，请稍候..."
  nsExec::ExecToStack '$UninstallNpmCmd uninstall -g openclaw'
  Pop $0
  Pop $1
  DetailPrint "npm 退出码：$1"
  ${If} $1 != "0"
    DetailPrint $0
    MessageBox MB_OK|MB_ICONEXCLAMATION "OpenClaw 没有完全卸掉，可看卸载日志详情，或手动运行 npm uninstall -g openclaw。"
  ${Else}
    DetailPrint "OpenClaw 已卸载。"
  ${EndIf}
FunctionEnd

!endif

!macro customUnInstall
  ${If} ${Silent}
    Goto unOptsEnd
  ${EndIf}

  ${If} $UninstallOptAppData == "1"
    DetailPrint "正在删除用户数据..."
    RMDir /r "$APPDATA\${APP_FILENAME}"
    !ifdef APP_PRODUCT_FILENAME
      RMDir /r "$APPDATA\${APP_PRODUCT_FILENAME}"
    !endif
    !ifdef APP_PACKAGE_NAME
      RMDir /r "$APPDATA\${APP_PACKAGE_NAME}"
    !endif
  ${EndIf}

  ${If} $UninstallOptPyDeps == "1"
  ${OrIf} $UninstallOptOpenClaw == "1"
    Call un.DetectPyNpm
  ${EndIf}

  ${If} $UninstallOptPyDeps == "1"
    ${If} $UninstallPythonCmd == ""
      MessageBox MB_OK|MB_ICONINFORMATION "没有在本机找到 Python，依赖包没有删除。如需手动清理，请运行：pip uninstall -y fastapi uvicorn pydantic PyYAML httpx networkx numpy aiosqlite APScheduler bcrypt PyJWT websockets python-docx PyMuPDF openpyxl Pillow joblib scikit-learn"
    ${Else}
      Call un.RemovePyDeps
    ${EndIf}
  ${EndIf}

  ${If} $UninstallOptOpenClaw == "1"
    ${If} $UninstallNpmCmd == ""
      MessageBox MB_OK|MB_ICONINFORMATION "没有在本机找到 npm，OpenClaw 没有删除。如需手动清理，请运行：npm uninstall -g openclaw"
    ${Else}
      Call un.RemoveOpenClaw
    ${EndIf}
  ${EndIf}

  unOptsEnd:
!macroend
