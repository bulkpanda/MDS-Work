# PDF Report creation utils
from __future__ import annotations
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from typing import Any, Literal, Optional, Dict
from dataclasses import dataclass
from pathlib import Path
import yaml

# From overall reports, we can see that the columns are as follows:
colId = 'Student ID'
colNameG = 'Student Given Name'
colNameF = 'Student Family Name'
colDate = 'Date'
colCohort = 'Cohort'
colSubject = 'Subject'
colAge = 'Patient Age'
colPatient = 'Patient' # whether saw a patient or not
colRole = 'Role'
colCE = 'Critical incident'
colCEReason = 'CI Details'
colComplex = 'Complexity'
colClinicType = 'Clinic Type' # Fixed Pros, Removable Pros, Perio, Endo, Resto, Paeds, OMFS, Diag, General Practice
colClinicTypeText = 'Clinic Type_3_TEXT'
colFinished = 'Finished'
colResponseId= 'ResponseId'
colComments = 'Supervisor comments'
colComments2 = 'Further comments'
colClinicChoice = 'Sim or Clinic'



# Styles for the PDF report

pageSize = ( 11.69 * inch, 8.27 * 2 * inch) # page size
print(pageSize)
figSize = (pageSize[0] / 100, pageSize[1] / 100)
uniColor = '#010d44'
textcolor = "#4f5fb2"
# Define the margins
leftMargin = 0.5* inch
rightMargin = 0.5 * inch
topMargin = 1 * inch
bottomMargin = 1 * inch

# Define the styles for the headings
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='Center', alignment=1))  # Center alignment
headingStyle = ParagraphStyle('Heading1', parent=styles['Heading1'], fontSize=32, alignment=1)  # Centered
heading2Style = ParagraphStyle('Heading2', parent=styles['Heading2'], fontSize=28, alignment=1)  # Centered
subheadingStyleL = ParagraphStyle( name="Subheading",fontSize=24,fontName="Helvetica-Bold", leading=18,spaceAfter=12,textColor=uniColor,alignment=0)  # Left aligned
subheadingStyle = ParagraphStyle(name="Subheading", fontSize=24, fontName="Helvetica-Bold", leading=18,spaceAfter=12,textColor=uniColor,alignment=1)  # Centered
subsubheadingStyle = ParagraphStyle(name="NormalText", fontSize=12, fontName="Helvetica",leading=15,spaceAfter=6,textColor=textcolor,alignment=1)  # Centered
subsubheadingStyleL  = ParagraphStyle(name="NormalText", fontSize=12, fontName="Helvetica",leading=15,spaceAfter=6,textColor=textcolor,alignment=0)  # Left aligned
smallsubsubheadingStyleL = ParagraphStyle('Heading3', parent=styles['Heading3'], fontSize=13, alignment=0)  # Left aligned
smallsubsubheadingStyleC = ParagraphStyle('Heading3', parent=styles['Heading3'], fontSize=13, alignment=1)  # Centered
normalLargeStyleLeft = ParagraphStyle('NormalLarge', parent=styles['Normal'], fontSize=18, alignment=0)  # Left aligned
normalLargeStyleCenter = ParagraphStyle('NormalLarge2', parent=styles['Normal'], fontSize=18, alignment=1)  # Center aligned
tableTextStyle = ParagraphStyle('LargeFont', parent=styles['Normal'], fontSize=13, alignment=1)
tableTextStyleL = ParagraphStyle('LargeFont', parent=styles['Normal'], fontSize=13, alignment=0)
tableTextStyleLSmall = ParagraphStyle('LargeFont', parent=styles['Normal'], fontSize=11, alignment=0)
tableTextStyleSmall= ParagraphStyle('SmallFont', parent=styles['Normal'], fontSize=11, alignment=1)
tableTextStyleLarge = ParagraphStyle('LargeFont', parent=styles['Normal'], fontSize=15, alignment=1, leading=20)
Checklistcolors = {'Yes': 'blue', 'No': 'orange', 'Not Reviewed': 'lightgrey'}


bannerHeadingStyle = ParagraphStyle(name='BannerHeading',fontName='Helvetica-Bold', fontSize=18,
    textColor='white',alignment=0,leading=22,spaceAfter=0,spaceBefore=0)

studentEmailFile = r'C:\Users\Kunal Patel\D folder\MDS Work\2026\RE_ Student List.xlsx'
itemSectionMappingFile = r'C:\Users\Kunal Patel\D folder\MDS Work\2026\item_section_mapping.xlsx'
# some utils for loading the schema.yaml and providing convenient access to tables, columns, types etc. as variables in code (instead of hardcoding strings everywhere). Also auto-reloads if the file changes on disk.
schemaPath  = 'schema.yaml'  # relative to this file
class Dot:
    """
    Dict -> attribute access wrapper.
    - d.foo -> d["foo"]
    - preserves nested structure
    """
    def __init__(self, data: Dict[str, Any], path: str = ""):
        self._data = data
        self._path = path

    def __getattr__(self, key: str) -> Any:
        if key not in self._data:
            raise AttributeError(f"Missing '{key}' at {self._path or 'root'}; keys={list(self._data.keys())}")
        val = self._data[key]
        if isinstance(val, dict):
            return Dot(val, path=f"{self._path}.{key}" if self._path else key)
        return val

    def get(self, key: str, default: Any = None) -> Any:
        val = self._data.get(key, default)
        if isinstance(val, dict):
            return Dot(val, path=f"{self._path}.{key}" if self._path else key)
        return val

    def dictkeys(self):
        return self._data.keys()


@dataclass(frozen=True)
class Schema:
    raw: Dot
    tables: Dot
    types: Dot
    commonColumns: Dot

    # convenience: Schema.table("raw_form_forms") -> Dot node
    def table(self, tableName: str) -> Dot:
        tablesDict = self.raw.tables._data  # type: ignore[attr-defined]
        if tableName not in tablesDict:
            raise KeyError(f"Unknown table '{tableName}'. Known: {list(tablesDict.keys())}")
        return Dot(tablesDict[tableName], path=f"tables.{tableName}")


_schemaCache: Optional[Schema] = None
_schemaMtime: Optional[float] = None


def loadSchema(schemaPath: str = schemaPath, reloadIfChanged: bool = True) -> Schema:
    global _schemaCache, _schemaMtime

    p = Path(schemaPath)
    mtime = p.stat().st_mtime

    if _schemaCache is None:
        reloadIfChanged = True

    if reloadIfChanged and (_schemaMtime is None or mtime != _schemaMtime):
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        root = Dot(data, path="root")
        _schemaCache = Schema(
            raw=root,
            tables=root.tables,
            types=root.types,
            commonColumns=root.commonColumns,
        )
        _schemaMtime = mtime

    return _schemaCache  # type: ignore[return-value]


# public singletons (auto-refresh on access via .schema)
class SchemaProxy:
    def __getattr__(self, key: str) -> Any:
        return getattr(loadSchema(), key)

schema = SchemaProxy()


# convenience variables that feel like your old style:
class TablesProxy:
    def __getattr__(self, tableKey: str) -> str:
        return getattr(loadSchema().tables, tableKey).get("name", tableKey)  # type: ignore

Tables = TablesProxy()

class ColsProxy:
    def __getattr__(self, tableKey: str) -> Dot:
        # returns columns node for that table
        return loadSchema().tables.__getattr__(tableKey).columns  # type: ignore

Cols = ColsProxy()


# # variables for the Postgres processing
# SqlType = Literal["BIGINT", "TEXT", "BOOLEAN", "TIMESTAMPTZ", "DATE", "JSONB", "FLOAT", "INT"]

# class ColumnDefinition:
#     def __init__(self, name: str, type_: SqlType, nullable: bool = True):
#         self.name = name
#         self.type_ = type_
#         self.nullable = nullable

# class Tables:
#     boh3dds4Forms = 'dds4_boh3_forms'
#     rawForms = 'raw_forms'
#     rawFormForms = 'raw_form_forms'

# class CommonCols:
#     assessmentId = 'assessmentid'
#     formCode = 'form_code'
#     cohort = 'cohort'
#     subject = 'subject'
#     date = 'date'
#     type_ = 'type'
#     datetimeutc = 'datetimeutc'
#     studentId = 'student_number'
#     studentName = 'student_name'
#     studentEmail = 'student_email'
#     version = 'version'
#     clinic = 'clinic'
#     assessorName = 'assessor_name'
#     submittedByStudent = 'submitted_by_student'
#     submittedByAssessor = 'submitted_by_assessor'
#     insertedAt = 'insertedat'

# class dds4boh3Columns(CommonCols):
#     rotation = 'rotation'
#     createdAt = 'createdat'
#     updatedAt = 'updatedat'
#     patientData = 'patient_data'
#     studentData = 'student_data'
#     assessorData = 'assessor_data'
#     studentConfig = 'student_config'
#     assessorConfig = 'assessor_config'
#     externalClinic = 'external_clinic'
#     additionalConcerns = 'additional_concerns'

# class formColumns(CommonCols):
#     studentReflection = 'student_reflection'
#     assessorReflection = 'assessor_reflection'
#     clinicalIncident = 'clinical_incident'
#     studentData = 'student_data'
#     assessorData = 'assessor_data'
#     patientComplexity = 'patient_complexity'
#     role = 'role'
#     scales = 'scales'
#     checklists = 'checklists'
#     patientAge = 'patient_age'
#     patientDrn = 'patient_drn'
#     patientDetails = 'patient_details'
#     additionalChecklists = 'additional_checklists'