Option Explicit

Dim shell
Dim fso
Dim appDir
Dim command

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
command = "pythonw.exe " & Chr(34) & fso.BuildPath(appDir, "indicator.py") & Chr(34)

shell.Run command, 0, False

