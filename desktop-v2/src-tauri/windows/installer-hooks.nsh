; Hooks for Tauri's NSIS installer (bundle.windows.nsis.installerHooks).
; The template inserts them in its Install and Uninstall sections.

; keyring names each session token's credential "<server>.<identifier>".
!define ONYX_CREDENTIAL_SUFFIX ".app.onyx.desktop.v2"
!define ONYX_CRED_TYPE_GENERIC 1
; ERROR_ELEVATION_REQUIRED and ERROR_PRODUCT_VERSION, so that deployment
; scripts can see why a silent install failed.
!define ONYX_EXIT_NOT_ADMIN 740
!define ONYX_EXIT_MSI_INSTALLED 1638

!macro NSIS_HOOK_PREINSTALL
  ; A standard user cannot write to Program Files. Without this check, a
  ; silent install as a standard user installs nothing and exits with 0.
  System::Call 'shell32::IsUserAnAdmin() i .r0'
  ${If} $0 = 0
    MessageBox MB_ICONSTOP "${PRODUCTNAME} installs for all users. Run the installer as an administrator." /SD IDOK
    SetErrorLevel ${ONYX_EXIT_NOT_ADMIN}
    Quit
  ${EndIf}

  ; The MSI installs into the same folder. Two installs there give two
  ; entries in Apps, and removing one breaks the other.
  Call FindWixInstall
  ${If} $R6 != ""
    MessageBox MB_ICONSTOP "${PRODUCTNAME} is already installed from the MSI package. Uninstall it in Settings > Apps, then run this installer again." /SD IDOK
    SetErrorLevel ${ONYX_EXIT_MSI_INSTALLED}
    Quit
  ${EndIf}
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

!macro NSIS_HOOK_POSTUNINSTALL
  ; "Delete the application data" also removes the session tokens. Windows
  ; keeps them in the user's Credential Manager, not in the app's folders.
  ; Another account's credentials are never touched.
  ${If} $DeleteAppDataCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
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
