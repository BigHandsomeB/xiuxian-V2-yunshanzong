Option Explicit
Dim shell, files, root, pythonw
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\.venv\Scripts\pythonw.exe"
shell.CurrentDirectory = root
If files.FileExists(pythonw) Then
    shell.Run Chr(34) & pythonw & Chr(34) & " -X utf8 -m tools.asset_manager.desktop", 0, False
Else
    shell.Run Chr(34) & root & "\start-asset-manager.cmd" & Chr(34), 1, False
End If
