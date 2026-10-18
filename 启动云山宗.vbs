Option Explicit
Dim shell, files, root, pythonw, package
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\.venv\Scripts\pythonw.exe"
package = root & "\.venv\Lib\site-packages\PySide6\__init__.py"
shell.CurrentDirectory = root
If files.FileExists(pythonw) And files.FileExists(package) And files.FileExists(root & "\.game\save-id") Then
    shell.Run Chr(34) & pythonw & Chr(34) & " -X utf8 -m tools.playable.desktop", 0, False
Else
    shell.Run Chr(34) & root & "\start-desktop.cmd" & Chr(34), 1, False
End If
