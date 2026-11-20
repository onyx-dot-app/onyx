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

!macro NSIS_HOOK_POSTUNINSTALL
  ; "Delete the application data" also removes the session tokens. Windows
  ; keeps them in the user's Credential Manager, not in the app's folders.
  ${If} $DeleteAppDataCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
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
