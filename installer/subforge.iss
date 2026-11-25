; Inno Setup 6 script for subtitle-forge.  Build:  scripts\build_installer.ps1 [-Variant full|lite]
; Same binaries as the portable zip (dist\subforge-portable[-lite]\), minus portable.flag so the
; installed app keeps its data (models, output, logs) in %LOCALAPPDATA%\subforge, not in Program Files.
#ifndef Variant
  #define Variant "full"
#endif
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#if Variant == "full"
  #define SrcDir "..\dist\subforge-portable"
#else
  #define SrcDir "..\dist\subforge-portable-lite"
#endif
#define RepoUrl "https://github.com/AgentRayx/Agent_Traductor"

[Setup]
AppId={{6F3A1C52-5B7E-4E0D-9A55-5B2D5C0F7A11}
AppName=subtitle-forge
AppVersion={#AppVersion}
AppPublisher=subtitle-forge contributors
AppPublisherURL={#RepoUrl}
AppSupportURL={#RepoUrl}/issues
AppUpdatesURL={#RepoUrl}/releases
DefaultDirName={autopf}\subtitle-forge
DefaultGroupName=subtitle-forge
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=subforge-{#AppVersion}-win64-setup-{#Variant}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayName=subtitle-forge ({#Variant})
DisableProgramGroupPage=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "addtopath"; Description: "Add subforge to the PATH (use it from any terminal)"; Flags: checkedonce

[Files]
Source: "{#SrcDir}\*"; DestDir: "{app}"; Excludes: "portable.flag"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\subforge (web UI)"; Filename: "{app}\subforge.exe"; Parameters: "ui"; WorkingDir: "{app}"; Comment: "Starts the local UI at http://127.0.0.1:8765"
Name: "{group}\subforge (terminal)"; Filename: "{cmd}"; Parameters: "/k ""cd /d %USERPROFILE% & set PATH={app};%PATH% & subforge.exe --help"""; Comment: "Command prompt with subforge ready"
Name: "{group}\README"; Filename: "{app}\README.txt"
Name: "{group}\Uninstall subtitle-forge"; Filename: "{uninstallexe}"

[Registry]
Root: HKA; Subkey: "{code:EnvKey}"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; \
    Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\subforge.exe"; Parameters: "--version"; Flags: runhidden; Description: "Self-check"

[Code]
function EnvKey(Param: string): string;
begin
  if IsAdminInstallMode then
    Result := 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
  else
    Result := 'Environment';
end;

function NeedsAddPath(Dir: string): Boolean;
var
  Paths: string;
begin
  if not RegQueryStringValue(HKA, EnvKey(''), 'Path', Paths) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Paths) + ';') = 0;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Paths, Dir: string;
  P: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Dir := ExpandConstant('{app}');
    if RegQueryStringValue(HKA, EnvKey(''), 'Path', Paths) then
    begin
      P := Pos(';' + Uppercase(Dir), Uppercase(Paths));
      if P > 0 then
      begin
        Delete(Paths, P, Length(Dir) + 1);
        RegWriteExpandStringValue(HKA, EnvKey(''), 'Path', Paths);
      end;
    end;
  end;
end;
