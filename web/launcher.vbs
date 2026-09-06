Dim fso, webDir
Set fso = CreateObject("Scripting.FileSystemObject")
webDir = fso.GetParentFolderName(WScript.ScriptFullName)
CreateObject("Wscript.Shell").Run """C:\Windows\System32\mshta.exe"" """ & webDir & "\launcher.hta""", 1, False
