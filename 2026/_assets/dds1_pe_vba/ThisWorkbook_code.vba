Option Explicit

' DDS1 PE report: click a student name in the side list on "Student Tracker"
' to load that student (sets the yellow pick cell; all tables and charts are formulas).
Private Sub Workbook_SheetSelectionChange(ByVal Sh As Object, ByVal Target As Range)
    On Error GoTo done
    If Sh.Name <> "Student Tracker" Then Exit Sub
    If Target.CountLarge <> 1 Then Exit Sub
    If Intersect(Target, Sh.Range("StudentPickList")) Is Nothing Then Exit Sub
    If Len(CStr(Target.Value)) = 0 Then Exit Sub
    If CStr(Sh.Range("StudentPick").Value) = CStr(Target.Value) Then Exit Sub
    Application.EnableEvents = False
    Sh.Range("StudentPick").Value = Target.Value
done:
    Application.EnableEvents = True
End Sub
