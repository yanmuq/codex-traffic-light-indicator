Option Explicit

Dim shell
Dim fso
Dim appDir
Dim command
Dim env
Dim tclLibrary
Dim tkLibrary

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set env = shell.Environment("Process")
Dim pythonw
pythonw = shell.ExpandEnvironmentStrings("%CODEX_TRAFFIC_LIGHT_PYTHONW%")
If pythonw = "%CODEX_TRAFFIC_LIGHT_PYTHONW%" Or Not fso.FileExists(pythonw) Then
    pythonw = "C:\Python313\pythonw.exe"
End If
If Not fso.FileExists(pythonw) Then
    pythonw = fso.BuildPath(appDir, "python-runtime-release\pythonw.exe")
End If
If Not fso.FileExists(pythonw) Then
    pythonw = "pythonw.exe"
End If
tclLibrary = shell.ExpandEnvironmentStrings("%CODEX_TRAFFIC_LIGHT_TCL_LIBRARY%")
tkLibrary = shell.ExpandEnvironmentStrings("%CODEX_TRAFFIC_LIGHT_TK_LIBRARY%")
If tclLibrary = "%CODEX_TRAFFIC_LIGHT_TCL_LIBRARY%" Or Not fso.FolderExists(tclLibrary) Then
    tclLibrary = "C:\Python313\tcl\tcl8.6"
    tkLibrary = "C:\Python313\tcl\tk8.6"
End If
If Not fso.FolderExists(tclLibrary) Then
    tclLibrary = fso.BuildPath(appDir, "python-runtime-release\tcl\tcl8.6")
    tkLibrary = fso.BuildPath(appDir, "python-runtime-release\tcl\tk8.6")
End If
If fso.FolderExists(tclLibrary) Then
    env("TCL_LIBRARY") = tclLibrary
    env("TK_LIBRARY") = tkLibrary
End If
command = Chr(34) & pythonw & Chr(34) & " " & Chr(34) & fso.BuildPath(appDir, "indicator.py") & Chr(34)

shell.Exec command
