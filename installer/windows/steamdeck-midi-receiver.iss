#define AppName "STEAMDECK MIDI Receiver"
#define AppExeName "STEAMDECK-MIDI-RECEIVER.exe"
#ifndef AppVersion
#define AppVersion "0.1.0"
#endif
#define AppPublisher "ViddySlap"
#define AppURL "https://github.com/ViddySlap/steam-deck-vj"

[Setup]
AppId={{7A0E5D8E-8F37-4FD0-A998-E5CE0D95D9CC}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
VersionInfoVersion={#AppVersion}
VersionInfoProductVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Setup
VersionInfoProductName={#AppName}
VersionInfoProductTextVersion={#AppVersion}
DefaultDirName={autopf}\STEAMDECK MIDI Receiver
DefaultGroupName={#AppName}
SetupIconFile=..\..\assets\windows\appicon.ico
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir=..\..\installer-output
OutputBaseFilename=STEAMDECK-MIDI-RECEIVER-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\..\dist\STEAMDECK-MIDI-RECEIVER.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\config\windows_midi_map.json"; DestDir: "{app}\config"; Flags: ignoreversion
Source: "..\..\config\windows_midi_map.json"; DestDir: "{app}\config"; DestName: "windows_midi_map.local.json"; Flags: onlyifdoesntexist
Source: "..\..\config\windows_receiver_settings.example.json"; DestDir: "{app}\config"; Flags: ignoreversion
Source: "..\..\config\windows_receiver_settings.example.json"; DestDir: "{app}\config"; DestName: "windows_receiver_settings.local.json"; Flags: onlyifdoesntexist
Source: "..\..\scripts\windows\start_installed_receiver.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\STEAMDECK MIDI Receiver"; Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -NoLogo -NoExit -File ""{app}\scripts\start_installed_receiver.ps1"" -InstallRoot ""{app}"""; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"
Name: "{group}\STEAMDECK MIDI Receiver"; Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -NoLogo -NoExit -File ""{app}\scripts\start_installed_receiver.ps1"" -InstallRoot ""{app}"""; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"

[Run]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -NoLogo -NoExit -File ""{app}\scripts\start_installed_receiver.ps1"" -InstallRoot ""{app}"""; Description: "Launch STEAMDECK MIDI Receiver"; Flags: nowait postinstall skipifsilent
