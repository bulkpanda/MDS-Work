# PDF Report creation utils
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
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
colClinicOther = 'Sim or Clinic_999_TEXT'

colServiceDiag =  'Diagnostics'

colServicePaed = 'Paeds specific'

colServiceOral = 'OMFS Sim/Clinic'

colServiceProsthoRemovClinic = 'Rem Pros CLINIC'

colServiceGeneral = 'General services'

colServicePPBClinic = 'Prevention CLINIC'
colServicePPBSim = 'Prevention SIM'
colServicePPB = 'Preventive, Prophylactic and Bleaching Services'

colServicePerioClinic = 'Perio CLINIC'
colServicePerioSim = 'Perio SIM'
colServicePerio = 'Periodontics'


colServiceEndoSim = 'Endo SIM'
colServiceEndoClinic = 'Endo CLINIC'
colServiceEndo = 'Endodontics'


colServiceRestorClinic = 'Resto CLINIC'
colServiceRestorSim = 'Resto SIM'
colServiceRestor = 'Restorative Services'


colServiceProsthoClinic = 'Fixed Pros Clinic'
colServiceProsthoSim = 'Fixed Pros SIM'
colServiceProstho = 'Fixed Prosthodontics'


colSupervisorChoice = 'CE Name'
colSupervisorOther = 'CE Name_37_TEXT'
colSupervisor = 'Clinical Educator Name'

serviceColMerge = [
    ([colServicePPBClinic, colServicePPBSim], colServicePPB),
    ([colServicePerioClinic, colServicePerioSim], colServicePerio),
    ([colServiceEndoSim, colServiceEndoClinic], colServiceEndo),
    ([colServiceRestorClinic, colServiceRestorSim], colServiceRestor),
    ([colServiceProsthoClinic, colServiceProsthoSim], colServiceProstho)
]

# reassign the column names
newServiceCols = [i[1] for i in serviceColMerge]
unChangedServiceCols = [colServiceDiag, colServiceOral, colServiceGeneral, colServiceProsthoRemovClinic, colServicePaed]
serviceCols = unChangedServiceCols + newServiceCols
checklistMap = {
'Positioning': 'PEC',
'Infection control': 'ICC',
'Record keeping': 'RKC',
'Consent': 'CC'
}
# Get list of column names based on the type
rubricQues = ['PS', 'CS', 'TS',	'ES']
newRubricQuesPatterns = ['PS-', 'CS-', 'TS-', 'ES-']

beforeCols = [colId, colNameG, colNameF, colDate]
afterCols = [colCohort, colSubject, colClinicChoice, colClinicOther, colCE, colCEReason, colPatient, colComplex, colAge, colCohort, colSubject, colRole, colClinicType, colClinicTypeText, colFinished, colSupervisor, colComments, colResponseId, colComments2]+ serviceCols

columnRenameFile = 'data/Column Rename Dictionary.json'

VALID_TAGS= ['SIM', 'Sim', 'CLINIC', 'Clinic', 'Infiltration', 'Block', 'Relining insert', 'Relining partial', 'Relining full',
                 'Review', 'Finish', 'Try-in', 'Occlusal', 'Secondary', 'Primary']

invalidIDs = [111111, 1111111, 1, 12, 123, 1234, 12345, 123456, 1234567, 12345678, 12321321, 0, 111, 12344]

mcReferenceFile = "data/MC Reference Dictionary.json"
othermcReferenceFile = 'data/MC Reference Other Dictionary.json'

notReviewedW = 0.5
mcScoreW = 0.8
rubricScoreW = 1 - mcScoreW



pageSize = ( 11.69 * inch, 8.27 * 2 * inch) # page size
print(pageSize)
figSize = (pageSize[0] / 100, pageSize[1] / 100)

# Define the margins
leftMargin = 0.5* inch
rightMargin = 0.5 * inch
topMargin = 1 * inch
bottomMargin = 0 * inch

# Define the styles for the headings
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='Center', alignment=1))  # Center alignment
headingStyle = ParagraphStyle('Heading1', parent=styles['Heading1'], fontSize=32, alignment=1)  # Centered
heading2Style = ParagraphStyle('Heading2', parent=styles['Heading2'], fontSize=28, alignment=1)  # Centered
subheadingStyle = ParagraphStyle('Heading2', parent=styles['Heading2'], fontSize=24, alignment=1)  # Centered
subsubheadingStyle = ParagraphStyle('Heading3', parent=styles['Heading3'], fontSize=20, alignment=1)  # Centered
subsubheadingStyleL = ParagraphStyle('Heading3', parent=styles['Heading3'], fontSize=20, alignment=0)  # Centered
normalLargeStyleLeft = ParagraphStyle('NormalLarge', parent=styles['Normal'], fontSize=18, alignment=0)  # Left aligned
normalLargeStyleCenter = ParagraphStyle('NormalLarge2', parent=styles['Normal'], fontSize=18, alignment=1)  # Center aligned
tableTextStyle = ParagraphStyle('LargeFont', parent=styles['Normal'], fontSize=13, alignment=1)
tableTextStyleL = ParagraphStyle('LargeFont', parent=styles['Normal'], fontSize=13, alignment=0)
tableTextStyleSmall= ParagraphStyle('SmallFont', parent=styles['Normal'], fontSize=11, alignment=1)
tableTextStyleLarge = ParagraphStyle('LargeFont', parent=styles['Normal'], fontSize=15, alignment=1, leading=20)
Checklistcolors = {'Yes': 'blue', 'No': 'orange', 'Not Reviewed': 'lightgrey'}
# Set the colorblind-friendly palette