' Launch the G3M PRO battery tray without showing a console window.
' Double-click this file to start the tray icon + floating window.
Option Explicit

Dim sh, fso, here, script, pyw, candidates, i, local

Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

here = fso.GetParentFolderName(WScript.ScriptFullName)
script = fso.BuildPath(here, "battery_tray.pyw")

If Not fso.FileExists(script) Then
    MsgBox "battery_tray.pyw not found:" & vbCrLf & script, 16, "G3M Battery"
    WScript.Quit 1
End If

' Prefer an explicit pythonw.exe so this works even when Python is not on PATH.
pyw = ""
local = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%")

candidates = Array( _
    local & "\Programs\Python\Python314\pythonw.exe", _
    local & "\Programs\Python\Python313\pythonw.exe", _
    local & "\Programs\Python\Python312\pythonw.exe", _
    local & "\Programs\Python\Python311\pythonw.exe", _
    "C:\Python314\pythonw.exe", _
    "C:\Python313\pythonw.exe", _
    "C:\Python312\pythonw.exe" )

For i = 0 To UBound(candidates)
    If fso.FileExists(candidates(i)) Then
        pyw = candidates(i)
        Exit For
    End If
Next

If pyw = "" Then pyw = "pythonw.exe"   ' last resort: rely on PATH

sh.CurrentDirectory = here
sh.Run """" & pyw & """ """ & script & """", 0, False
