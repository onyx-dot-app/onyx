; Hooks for Tauri's NSIS installer (bundle.windows.nsis.installerHooks).
; The template inserts the macros in its Install and Uninstall sections and
; includes this file before it defines its pages.

; keyring names each session token's credential "<server>.<identifier>".
!define ONYX_CREDENTIAL_SUFFIX ".app.onyx.desktop"
!define ONYX_CRED_TYPE_GENERIC 1
; ERROR_ELEVATION_REQUIRED and ERROR_PRODUCT_VERSION, so that deployment
; scripts can see why a silent install failed.
!define ONYX_EXIT_NOT_ADMIN 740
!define ONYX_EXIT_MSI_INSTALLED 1638
!define ONYX_ATTRIBUTE_DIRECTORY 0x10
!define ONYX_ATTRIBUTE_REPARSE_POINT 0x400

; 1 when the uninstall deletes the application data.
Var OnyxDeleteAppData

; The MSI installs into the same folder. Two installs there give two entries
; in Apps, and removing one breaks the other. $(^Name) because PRODUCTNAME is
; defined after this file is included.
!macro OnyxStopIfMsiInstalled
  Call FindWixInstall
  ${If} $R6 != ""
    MessageBox MB_ICONSTOP "$(^Name) is already installed from the MSI package. Uninstall it in Settings > Apps, then run this installer again." /SD IDOK
    SetErrorLevel ${ONYX_EXIT_MSI_INSTALLED}
    Quit
  ${EndIf}
!macroend

; The template's reinstall page uninstalls an MSI install when the user goes on,
; so an interactive (or /P) install stops before the first page. A silent
; install shows no pages and stops in NSIS_HOOK_PREINSTALL.
!define MUI_CUSTOMFUNCTION_GUIINIT OnyxGuiInit
Function OnyxGuiInit
  !insertmacro OnyxStopIfMsiInstalled
FunctionEnd

; The earlier desktop app's setup program installed for the current user
; only, with its uninstall entry under HKCU. Left in place, it would be a
; second Onyx in Apps, and its per-user onyx:// entry would win over this
; install's. Its silent uninstall keeps its data folders. Only the user who
; runs this installer is covered; a LocalSystem install finds nothing here.
!macro OnyxRemoveEarlierUserInstall
  Push $R0
  Push $R1
  Push $R2
  ReadRegStr $R0 HKCU "${UNINSTKEY}" "UninstallString"
  ${If} $R0 != ""
    ; The value is the quoted path of uninstall.exe.
    StrCpy $R1 $R0 1
    ${If} $R1 == '"'
      StrCpy $R0 $R0 "" 1
      StrCpy $R0 $R0 -1
    ${EndIf}
    ${GetParent} "$R0" $R1
    ${If} ${FileExists} "$R0"
    ${AndIf} $R1 != "$INSTDIR"
      DetailPrint "Removing the earlier per-user install in $R1"
      ; _?= runs the uninstaller in place, so ExecWait waits for it.
      ClearErrors
      ExecWait '"$R0" /S _?=$R1' $R2
      ${IfNot} ${Errors}
      ${AndIf} $R2 = 0
        Delete "$R0"
        RMDir "$R1"
      ${Else}
        DetailPrint "Could not remove the earlier per-user install (exit code $R2)."
      ${EndIf}
    ${EndIf}
  ${EndIf}
  Pop $R2
  Pop $R1
  Pop $R0
!macroend

!macro NSIS_HOOK_PREINSTALL
  ; A standard user cannot write to Program Files. Without this check, a
  ; silent install as a standard user installs nothing and exits with 0.
  System::Call 'shell32::IsUserAnAdmin() i .r0'
  ${If} $0 = 0
    MessageBox MB_ICONSTOP "${PRODUCTNAME} installs for all users. Run the installer as an administrator." /SD IDOK
    SetErrorLevel ${ONYX_EXIT_NOT_ADMIN}
    Quit
  ${EndIf}

  !insertmacro OnyxStopIfMsiInstalled
  !insertmacro OnyxRemoveEarlierUserInstall
!macroend

; Sets $0 to 1 if the uninstaller runs as the user who owns the desktop, else
; to 0. With another administrator's credentials, the uninstaller runs as that
; administrator, and the desktop user's credentials are out of reach.
Function un.OnyxRunsAsDesktopUser
  StrCpy $0 0
  System::Call 'user32::GetShellWindow() p .r1'
  ${If} $1 <> 0
    System::Call 'user32::GetWindowThreadProcessId(p r1, *i .r2)'
    ; PROCESS_QUERY_LIMITED_INFORMATION
    System::Call 'kernel32::OpenProcess(i 0x1000, i 0, i r2) p .r3'
    ${If} $3 <> 0
      ; TOKEN_QUERY
      System::Call 'advapi32::OpenProcessToken(p r3, i 8, *p .r4) i .r5'
      ${If} $5 <> 0
        System::Call 'kernel32::GetCurrentProcess() p .r6'
        System::Call 'advapi32::OpenProcessToken(p r6, i 8, *p .r6) i .r5'
        ${If} $5 <> 0
          System::Alloc 256
          Pop $7
          System::Alloc 256
          Pop $8
          ; TokenUser: a TOKEN_USER, which starts with the user's SID.
          System::Call 'advapi32::GetTokenInformation(p r4, i 1, p r7, i 256, *i .r9) i .r5'
          ${If} $5 <> 0
            System::Call 'advapi32::GetTokenInformation(p r6, i 1, p r8, i 256, *i .r9) i .r5'
            ${If} $5 <> 0
              System::Call '*$7(p .r1)'
              System::Call '*$8(p .r2)'
              System::Call 'advapi32::EqualSid(p r1, p r2) i .r5'
              ${IfThen} $5 <> 0 ${|} StrCpy $0 1 ${|}
            ${EndIf}
          ${EndIf}
          System::Free $7
          System::Free $8
          System::Call 'kernel32::CloseHandle(p r6)'
        ${EndIf}
        System::Call 'kernel32::CloseHandle(p r4)'
      ${EndIf}
      System::Call 'kernel32::CloseHandle(p r3)'
    ${EndIf}
  ${EndIf}
FunctionEnd

; Deletes the directory on the stack and its contents, as
; delete-user-data.ps1 does for the MSI. The uninstaller runs as an
; administrator, and the user can put links in these folders: a junction or
; symbolic link stays, and its target does not change. RMDir /r follows them.
; Each directory stays open without delete sharing while it is walked, so no
; process can rename it or put a link in its place. The open does not follow
; a link, and a directory that opens as a link is left alone.
; A directory is removed only when it is empty.
Function un.OnyxDeleteTree
  Exch $R0
  Push $R1
  Push $R2
  Push $R3
  Push $R4
  Push $R5
  Push $R6
  ; FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES, FILE_SHARE_READ |
  ; FILE_SHARE_WRITE, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS |
  ; FILE_FLAG_OPEN_REPARSE_POINT
  System::Call 'kernel32::CreateFileW(w R0, i 0x81, i 3, p 0, i 3, i 0x02200000, p 0) p .R5'
  ; BY_HANDLE_FILE_INFORMATION starts with the attributes.
  System::Alloc 52
  Pop $R6
  System::Call 'kernel32::GetFileInformationByHandle(p R5, p R6) i .R3'
  ${If} $R3 <> 0
    System::Call '*$R6(i .R3)'
  ${Else}
    StrCpy $R3 -1
  ${EndIf}
  System::Free $R6
  ; INVALID_FILE_ATTRIBUTES (-1) also has the reparse point bit.
  IntOp $R4 $R3 & ${ONYX_ATTRIBUTE_REPARSE_POINT}
  IntOp $R6 $R3 & ${ONYX_ATTRIBUTE_DIRECTORY}
  ${If} $R4 = 0
  ${AndIf} $R6 <> 0
    FindFirst $R1 $R2 "$R0\*"
    ${DoWhile} $R2 != ""
      ${If} $R2 != "."
      ${AndIf} $R2 != ".."
        StrCpy $R4 "$R0\$R2"
        System::Call 'kernel32::GetFileAttributesW(w R4) i .R3'
        IntOp $R4 $R3 & ${ONYX_ATTRIBUTE_REPARSE_POINT}
        ${If} $R4 <> 0
          ; Gone, or a link.
        ${Else}
          IntOp $R4 $R3 & ${ONYX_ATTRIBUTE_DIRECTORY}
          ${If} $R4 <> 0
            ; Checked again on its open handle.
            Push "$R0\$R2"
            Call un.OnyxDeleteTree
          ${Else}
            ; Delete never goes into a directory, and on a file link it
            ; removes only the link.
            Delete "$R0\$R2"
          ${EndIf}
        ${EndIf}
      ${EndIf}
      FindNext $R1 $R2
    ${Loop}
    FindClose $R1
    System::Call 'kernel32::CloseHandle(p R5)'
    ; Without /r: fails when the directory is not empty.
    RMDir "$R0"
  ${Else}
    System::Call 'kernel32::CloseHandle(p R5)'
  ${EndIf}
  Pop $R6
  Pop $R5
  Pop $R4
  Pop $R3
  Pop $R2
  Pop $R1
  Pop $R0
FunctionEnd

; Deletes the app folder on the stack. When the folder is itself a link, it
; removes only the link: RMDir without /r does not go into it.
Function un.OnyxDeleteAppFolder
  Exch $R0
  Push $R1
  System::Call 'kernel32::GetFileAttributesW(w R0) i .R1'
  ${If} $R1 <> -1
    IntOp $R1 $R1 & ${ONYX_ATTRIBUTE_REPARSE_POINT}
    ${If} $R1 <> 0
      RMDir "$R0"
    ${Else}
      Push $R0
      Call un.OnyxDeleteTree
    ${EndIf}
  ${EndIf}
  Pop $R1
  Pop $R0
FunctionEnd

; The template deletes the app folders with RMDir /r after the files, when
; "Delete the application data" is checked. This hook takes the option over,
; so that the template's delete never runs.
!macro NSIS_HOOK_PREUNINSTALL
  StrCpy $OnyxDeleteAppData 0
  ${If} $DeleteAppDataCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
    StrCpy $OnyxDeleteAppData 1
  ${EndIf}
  StrCpy $DeleteAppDataCheckboxState 0
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  ${If} $OnyxDeleteAppData = 1
    ; What the template deletes for this option, without its RMDir /r.
    DeleteRegKey SHCTX "${MANUPRODUCTKEY}"
    DeleteRegKey /ifempty SHCTX "${MANUKEY}"
    DeleteRegValue HKCU "${MANUPRODUCTKEY}" "Installer Language"
    DeleteRegKey /ifempty HKCU "${MANUPRODUCTKEY}"
    DeleteRegKey /ifempty HKCU "${MANUKEY}"
    ; The folders of the user who runs the uninstaller, as in the template.
    SetShellVarContext current
    Push "$APPDATA\${BUNDLEID}"
    Call un.OnyxDeleteAppFolder
    Push "$LOCALAPPDATA\${BUNDLEID}"
    Call un.OnyxDeleteAppFolder
  ${EndIf}

  ; "Delete the application data" also removes the session tokens. Windows
  ; keeps them in the user's Credential Manager, not in the app's folders.
  ; Another account's credentials are never touched.
  ${If} $OnyxDeleteAppData = 1
    Call un.OnyxRunsAsDesktopUser
  ${Else}
    StrCpy $0 0
  ${EndIf}
  ${If} $0 = 1
    ; $1: number of credentials, $2: array of PCREDENTIALW.
    System::Call 'advapi32::CredEnumerateW(p 0, i 0, *i .r1, *p .r2) i .r0'
    ${If} $0 <> 0
      StrLen $9 "${ONYX_CREDENTIAL_SUFFIX}"
      IntOp $9 0 - $9
      StrCpy $3 0
      ${While} $3 < $1
        IntOp $4 $3 * ${NSIS_PTR_SIZE}
        IntPtrOp $4 $2 + $4
        System::Call '*$4(p .r5)'
        ; CREDENTIALW starts with Flags, Type and TargetName.
        System::Call '*$5(i .r6, i .r7, w .r8)'
        StrCpy $R9 $8 "" $9
        ${If} $7 = ${ONYX_CRED_TYPE_GENERIC}
        ${AndIf} $R9 == "${ONYX_CREDENTIAL_SUFFIX}"
          System::Call 'advapi32::CredDeleteW(w r8, i r7, i 0) i .r6'
        ${EndIf}
        IntOp $3 $3 + 1
      ${EndWhile}
      System::Call 'advapi32::CredFree(p r2)'
    ${EndIf}
  ${EndIf}
!macroend
