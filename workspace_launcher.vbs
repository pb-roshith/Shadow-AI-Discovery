Option Explicit
Dim shell, fso, root, python, action, command, result
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
If WScript.Arguments.Count <> 1 Then WScript.Quit 1
action = WScript.Arguments(0)
If action <> "start" And action <> "stop" Then WScript.Quit 1
python = root & "\shadow server\backend\.venv\Scripts\python.exe"
If Not fso.FileExists(python) Then
    MsgBox "Run setup.bat first.", 16, "Shadow AI workspace"
    WScript.Quit 1
End If
shell.CurrentDirectory = root
command = Chr(34) & python & Chr(34) & " " & Chr(34) & root & "\shadow server\backend\setup\workspace_services.py" & Chr(34) & " " & action & " --hidden"
result = shell.Run(command, 0, True)
If result <> 0 Then MsgBox "Could not " & action & " the workspace. See .runtime\launcher.log for details.", 16, "Shadow AI workspace"
WScript.Quit result
