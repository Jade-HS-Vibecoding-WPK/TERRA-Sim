; Inno Setup: Windows-Installer für TERRA-Sim.
;
;   iscc /DAppVersion=1.0 desktop\installer.iss
;
; Erwartet das fertige Programm in dist\TERRA-Sim (pyinstaller desktop\terra-sim.spec) und
; das Symbol desktop\icon.ico (python desktop\make_icon.py). Installiert nur für den
; aktuellen Benutzer – ohne Administratorrechte.

#ifndef AppVersion
  #define AppVersion "1.0"
#endif

[Setup]
AppId={{8C1B6E2A-4F1D-4B8E-9A55-7E3C2D9F0A11}
AppName=TERRA-Sim
AppVersion={#AppVersion}
AppVerName=TERRA-Sim {#AppVersion}
AppPublisher=Jade Hochschule – WPK Vibecoding
AppPublisherURL=https://github.com/Jade-HS-Vibecoding-WPK/TERRA-Sim
AppSupportURL=https://github.com/Jade-HS-Vibecoding-WPK/TERRA-Sim/issues
AppUpdatesURL=https://github.com/Jade-HS-Vibecoding-WPK/TERRA-Sim/releases
DefaultDirName={localappdata}\Programs\TERRA-Sim
DefaultGroupName=TERRA-Sim
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=TERRA-Sim-{#AppVersion}-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\TERRA-Sim.exe
UninstallDisplayName=TERRA-Sim {#AppVersion}
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\TERRA-Sim\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\TERRA-Sim"; Filename: "{app}\TERRA-Sim.exe"
Name: "{autodesktop}\TERRA-Sim"; Filename: "{app}\TERRA-Sim.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\TERRA-Sim.exe"; Description: "{cm:LaunchProgram,TERRA-Sim}"; Flags: nowait postinstall skipifsilent
