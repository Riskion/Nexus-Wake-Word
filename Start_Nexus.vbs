
Option Explicit

Dim FSO, WshShell, Folder, ScriptPath, PythonW
Dim VenvPython, Command, CudaBin, CudnnBin

Set FSO = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

Folder = FSO.GetParentFolderName(WScript.ScriptFullName)
ScriptPath = FSO.BuildPath(Folder, "note.py")
VenvPython = FSO.BuildPath(Folder, ".venv\Scripts\pythonw.exe")

If Not FSO.FileExists(ScriptPath) Then
    MsgBox "Cannot find note.py in:" & vbCrLf & Folder, vbExclamation, "Nexus"
    WScript.Quit 1
End If

If Not FSO.FileExists(VenvPython) Then
    MsgBox "Cannot find virtual-environment Python:" & vbCrLf & VenvPython & vbCrLf & vbCrLf & "Please check that .venv is installed correctly.", vbExclamation, "Nexus"
    WScript.Quit 1
End If

WshShell.CurrentDirectory = Folder

' Add NVIDIA CUDA runtime DLL folders to PATH.
CudaBin = FSO.BuildPath(Folder, ".venv\Lib\site-packages\nvidia\cublas\bin")
CudnnBin = FSO.BuildPath(Folder, ".venv\Lib\site-packages\nvidia\cudnn\bin")

If FSO.FolderExists(CudaBin) Then
    WshShell.Environment("Process")("PATH") = CudaBin & ";" & WshShell.Environment("Process")("PATH")
End If

If FSO.FolderExists(CudnnBin) Then
    WshShell.Environment("Process")("PATH") = CudnnBin & ";" & WshShell.Environment("Process")("PATH")
End If

Command = """" & VenvPython & """ """ & ScriptPath & """"
WshShell.Run Command, 0, False

Set WshShell = Nothing
Set FSO = Nothing
