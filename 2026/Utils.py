import pandas as pd
import re
import numpy as np
from pprint import pprint
import warnings
import openpyxl
import os
import variableUtils
import json
from openpyxl.utils import get_column_letter
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error
from matplotlib import pyplot as plt
from IPython.display import display
from reportlab.lib.pagesizes import letter, landscape, A4, A3
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, PageBreak, Paragraph, Image, Spacer
from io import BytesIO
from reportlab.lib import colors
from matplotlib.backends.backend_pdf import PdfPages
from reportlab.platypus import Table as RLTable, TableStyle
from reportlab.platypus import Paragraph, Spacer, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from PyPDF2 import PdfReader, PdfWriter
from reportlab.lib.enums import TA_CENTER
import datetime
from dateutil import parser
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from itertools import combinations
from sqlalchemy import create_engine, text
# For data cleaning and preprocessing

pdfmetrics.registerFont(TTFont('Arial', 'arial.ttf'))
pdfmetrics.registerFont(TTFont('Calibri-Bold', 'calibrib.ttf'))  # Bold version

def getFolderandFileName(filePath: str):
    """
    Gets the folder path and file name from a file path.

    Args:
        filePath (str): The path to the file.

    Returns:
        folderPath (str): The folder path containing the file.
        fileName (str): The name of the file.
    """
    folderPath, fileName = os.path.split(filePath)
    name, ext = os.path.splitext(fileName)
    return folderPath, name, ext

def convertDate(date_str):
    if isinstance(date_str, pd.Timestamp):
        return date_str.strftime('%d/%m/%Y')
    try:
        date_obj = parser.parse(date_str)
    except ValueError:
        print(f"Error parsing date: {date_str}, converting to datetime object")
        date_str = date_str.replace(' ', '')
        date_str = date_str.replace('th', '')
        date_str = date_str.replace('st', '')
        date_str = date_str.replace('nd', '')
        date_str = date_str.replace('rd', '')
        date_obj = parser.parse(date_str)
        print(f"Converted date: {date_obj}")
    except TypeError as e:
        print(f"TypeError: {e}")    
        date_obj = date_str
    print(f"Date: {date_obj}")
    return date_obj.strftime('%d/%m/%Y')

    """
    Loads an Excel workbook from the specified file path.
    
    Args:
        filePath (str): The path to the Excel file.
        
    Returns:
        workbook (openpyxl.Workbook): The loaded workbook object.
    """
    workbook = openpyxl.load_workbook(filePath, data_only=True)

    # Get folder path and file name
    folderPath, name, ext = getFolderandFileName(filePath)
    pprint(f"Loaded workbook: {folderPath} | {name} | {ext}")
    pprint(f"Workbook sheets: {workbook.sheetnames}")
    return workbook, folderPath, name

def getStudentList(listFile1 = 'data/Student ID for Kunal.xlsx', listFile2 = '2024/data/2024 MDS Student List_v10.xlsx', **kwargs):
    # Load the Excel file containing the student IDs
    # listDf1 = pd.read_excel(listFile1)
    # get cohort from kwargs
    cohort = kwargs.get('cohort', None)
    # if cohort is not None:
        # listDf1 = listDf1[listDf1['Cohort'] == cohort]
    # Get the student IDs as a list
    # studentList = list(listDf1[variableUtils.colId])

    # Load the Excel file containing the student IDs
    listDf2 = pd.read_excel(listFile2)
    if cohort is not None:
        listDf2 = listDf2[listDf2['Cohort'] == cohort]
    studentList = []
    # Get the student IDs as a list
    studentList += list(listDf2[variableUtils.colId])
    studentList = list(set(studentList))
    return studentList

def printDuplicateValues(renameDict):
    # Reverse the dictionary to group keys by their values
    reverseDict = {}
    for key, value in renameDict.items():
        if value in reverseDict:
            reverseDict[value].append(key)
        else:
            reverseDict[value] = [key]
    
    # Check for duplicates and print them
    duplicatesFound = False
    for value, keys in reverseDict.items():
        if len(keys) > 1:
            duplicatesFound = True
            print(f"Duplicate value: '{value}' found for keys: {keys}")
    
    if not duplicatesFound:
        print("No duplicate values found.")

def mergeAndDeleteOneColumn(df, col1, col2, newCol):
    """
    Merges two columns in a DataFrame and deletes the original columns.

    Args:
        df (pandas.DataFrame): The DataFrame containing the columns.
        col1 (str): The name of the first column to merge.
        col2 (str): The name of the second column to merge.
        newCol (str): The name of the new column to create.

    Returns:
        pandas.DataFrame: The DataFrame with the merged column and the original columns dropped.
    """
    # check if the columns exist in the DataFrame
    if col1 not in df.columns or col2 not in df.columns:
        return df
    # Create the new column by merging col1 and col2
    df[newCol] = df[col1].fillna('') + ', ' + df[col2].fillna('')
    # Remove trailing comma if one column is empty or NaN
    df[newCol] = df[newCol].str.strip(', ')
    # Drop the original columns
    df = df.drop(columns=[col1, col2])
    return df

def mergeColumns(df: pd.DataFrame, serviceColMerge: list):
    for cols, new_col in serviceColMerge:
        if len(cols) == 2:
            df = mergeAndDeleteOneColumn(df, cols[0], cols[1], new_col)
        else:
            raise ValueError("Each tuple must contain exactly two columns to merge.")
    return df

def convertRubricScale(df, rubricQues):
    for col in rubricQues:
        df[col] = df[col].str.extract(r'Lvl (\d+)')[0]
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype('Int64')
    return df

def vectoriseColumn(columnName, df, maxColValue, newRubricQues: set):
    df[columnName] = df[columnName].fillna(0).astype(int)
    for i in range(1, maxColValue + 1):
        df[f'{columnName}-{i}'] = (df[columnName] >= i).astype(int)
        newRubricQues.add(f'{columnName}-{i}')

def vectoriseRubricQues(df, rubricQues, newRubricQues):
    # vectorise the rubricQues
    for col in rubricQues:
        # print(df[col])
        maxColValue = int(df[col].max())
        # print(col, maxColValue)
        vectoriseColumn(col, df, maxColValue, newRubricQues)
        # df.drop(columns=[col], inplace=True)
    return df

def checkAttendence(workbookPath, cohort=None, studentListPath='2024 MDS Student List_v10.xlsx'):
    """
    Check the attendance of students in a given workbook.
    Parameters:
    - workbookPath (str): The path to the workbook file.
    - studentListPath (str): The path to the student list file. Default is '2024 MDS Student List_v10.xlsx'.
    - cohort (str): The cohort to filter the student list. Default is None.
    Returns:
    None
    Prints:
    - Students Attended: A list of unique student IDs who attended.
    - Students in Cohort: A list of unique student IDs in the specified cohort.
    - Students who did not attend: A list of student IDs who did not attend.
    """

    colCohort = variableUtils.colCohort
    colId = variableUtils.colId
    df = pd.read_excel(workbookPath)
    # df = loadDfFromSheet(workbook, 'Sheet0')
    # df = removeFirstRow(df)
    
    # Get list of students
    studentsAttended = df[colId].unique().astype(pd.Int64Dtype)
    print('Students Attended: ')
    pprint(studentsAttended)
    
    # Get list of students from student list
    studentDf = pd.read_excel(studentListPath)
    # selectionTupleList = [(colCohort, 'DDS2 (2024)')]
    studentDf = getDfbyColumnValue(studentDf, colCohort, cohort)
    students = studentDf[colId].unique().astype(pd.Int64Dtype)
    print('\nStudents in Cohort: ')
    pprint(students)
    # Get list of students who did not attend
    print('\nStudents who did not attend: ')
    for student in students:
        if student not in studentsAttended:
            print(student)

def getImportance(df, code, tag, folderPath, cohort=None):
    """
    Get the feature importances for the Random Forest Regressor model.
    """
    colCohort = variableUtils.colCohort
    rubricQues = variableUtils.rubricQues
    # If there are duplicate columns keep one of them
    df = df.loc[:, ~df.columns.duplicated()]
    if cohort is not None:
        newDf = df[df[colCohort]==cohort]
    else:
        newDf = df.copy()
    newDf.replace({'Yes': 1, 'No': 0, 'Not Assessed': np.nan, 'Not Reviewed': np.nan, 'Completed': 1, 'Not completed': 0, 'NA': np.nan}, inplace=True)
    display(newDf.head())
    display(newDf.columns)
    mc_columns_test = findMCColumns(newDf)
    # mc_columns_test = [col for col in mc_columns_test if 'supervisor' in col]
    newDf = newDf[mc_columns_test + rubricQues+ ['MC Total']]
    newDf[mc_columns_test] = newDf[mc_columns_test].replace('', pd.NA)
    newDf[mc_columns_test] = newDf[mc_columns_test].astype(pd.Int64Dtype())
    print(mc_columns_test)
    colmcTotal = 'MC Total'
    newDf[colmcTotal] = newDf[colmcTotal].replace('', pd.NA)
    newDf[colmcTotal] = newDf[colmcTotal].astype(pd.Int64Dtype())
    colmcTotalPossible = 'MC total possible'
    # newDf[colmcTotal] = newDf[mc_columns_test].sum(axis=1, skipna=True).astype(pd.Int64Dtype())
    newDf[colmcTotalPossible] = newDf[mc_columns_test].count(axis=1)
    newDf = newDf[(newDf[colmcTotalPossible]>5)]
    # display(newDf)
    colmcPercent= 'MC %'
    newDf[colmcPercent] = (newDf[colmcTotal]/newDf[colmcTotalPossible]*100)
    # display(newDf)
    newDf.to_csv(f'{folderPath}\\{code}.csv')
    
    # Drop the rows with missing values in the target column
    newDf = newDf.dropna(subset=[colmcPercent])
    # Split the data into training and testing sets

    X = newDf[mc_columns_test]
    y = newDf[colmcPercent]
    if len(y) < 5:
        print(f'Not enough data for {code} ({tag})')
        return

    # for col in rubricQues:
    #     newDf2 = newDf[newDf[col].notnull()]
    #     X = newDf2[mc_columns_test]
    #     y= newDf2[col]
    imputer = SimpleImputer(strategy='mean')
    X_imputed = imputer.fit_transform(X)
    X_train, X_test, y_train, y_test = train_test_split(X_imputed, y, test_size=0.2, random_state=42)

    # Train a Random Forest Regressor
    model = RandomForestRegressor(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)

    # Predict and evaluate the model
    y_pred = model.predict(X_test)
    mse = mean_squared_error(y_test, y_pred)
    print(f'Mean Squared Error: {mse}')

    # Get feature importances
    feature_importances = model.feature_importances_
    feature_names = X.columns

    # Create a DataFrame for visualization
    importance_df = pd.DataFrame({
        'Feature': feature_names,
        'Importance': feature_importances
    }).sort_values(by='Importance', ascending=False)

    # Plot the feature importances
    plt.figure(figsize=(10, 8))
    plt.barh(importance_df['Feature'], importance_df['Importance'])
    plt.xlabel('Importance')
    plt.ylabel('Feature')
    title = f'Feature Importances for {code} ({tag}) {cohort}' if cohort is not None else f'Feature Importances for {code} ({tag})'
    plt.title(title)
    plt.gca().invert_yaxis()
    plt.tight_layout()
    savepath = f'{folderPath}/{code}_{tag}_{cohort}_FeatureImportances.png' if cohort is not None else f'{folderPath}/{code}_{tag}_FeatureImportances.png'
    plt.savefig(savepath, bbox_inches='tight')
    plt.show()

    # Get counts of each type of value
    getMCValueCounts(df, code, tag, folderPath, cohort=cohort)

def autopct(pct, total):
    """
    Generate the autopct string for a pie chart.
    Parameters:
    - pct (float): The percentage value of the data point.
    - total (int): The total value of the data points.
    Returns:
    - str: The formatted autopct string.
    Example:
    >>> autopct(25, 100)
    '25%\n(25)'
    Usage: lambda pct: autopct(pct, total)
    """
    
    val = int(round(pct * total / 100.0))
    return '{:.0f}% \n({v:d})'.format(pct, v=val) if pct > 0 else ''

def anonymize_column(column):
    unique_values = column.dropna().unique()  # Get unique non-null values
    mapping = {str(value): idx for idx, value in enumerate(unique_values, start=1)}  # Create a mapping
    reverse_mapping = {idx: value for value, idx in mapping.items()}  # Reverse mapping for reference
    return column.map(mapping), mapping, reverse_mapping

def getPairCounts(df, colPairBy = variableUtils.colId, colPairWith = None):
    # Create a dictionary to count pairs
    pair_counts = {}

    # Group by Student ID
    grouped = df.groupby(colPairBy)

    # Loop through each group
    for _, group in grouped:
        # Get unique CE Names for each student
        ce_names = group[colPairWith].unique() if colPairWith is not None else group.unique()
        
        # Get all combinations of pairs (should be only one pair per student in this setup)
        pairs = list(combinations(sorted(ce_names), 2))
        
        for pair in pairs:
            if pair in pair_counts:
                pair_counts[pair] += 1
            else:
                pair_counts[pair] = 1

    # Convert the dictionary to a DataFrame
    pairs_df = pd.DataFrame(pair_counts.items(), columns=['Pair', '# of Pairs'])

    # Display the result
    display(pairs_df)
    return pairs_df

def createTable(df, title, colRatio:list, tableWidth = 0.9, customTextCols = [], 
            tableTextStyle = variableUtils.tableTextStyle, topPadding = 12, bottomPadding = 12, cellHighlight = False, headerColor = '#9C27B0', titleStyle = variableUtils.subsubheadingStyle,
            headerTextColor = '#FFFFFF', pageSize = variableUtils.pageSize):
    print(f'Creating table for {title}')
    if df.empty:
        table = Paragraph("No data found", variableUtils.subsubheadingStyle)
    else:
        data = [df.columns.to_list()] + df.values.tolist()
        
        # Convert the custom text columns to paragraphs
        for i in range(1, len(data)):
            for j in customTextCols:
                data[i][j] = Paragraph(str(data[i][j]), tableTextStyle)
        
        if colRatio is not None:
            colWidths = [ratio/sum(colRatio) * pageSize[0] * tableWidth for ratio in colRatio]
        else:
            colWidths = [1 for i in range(len(df.columns))] # Equal column widths
        # print(f'Column widths: {colWidths}')
        table = Table(data, colWidths=colWidths)
        # print(data)
        table_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(headerColor)),  # Header row
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor(headerTextColor)),  # Header text
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),  # Center align all cells
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),  # Center align all cells
            ('GRID', (0, 0), (-1, -1), 1, colors.black),  # Add border around cells
            # ('ALIGN', (3, 1), (3, -1), 'LEFT'),  # Left align Reason column cells
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),  # Change font to bold
            ('FONTSIZE', (0, 0), (-1, -1), 14),  # Increase font size
            ('BOTTOMPADDING', (0, 0), (-1, -1), bottomPadding),  # Increase bottom padding
            ('TOPPADDING', (0, 0), (-1, -1), topPadding),  # Increase top padding
        ])
        table.setStyle(table_style)

    mergedElement = KeepTogether([Paragraph(title, titleStyle), Spacer(1, 6), table, Spacer(1, 12)])

    # Add red colour where cell values are No
    if not cellHighlight:
        return mergedElement
    if df.empty:
        return mergedElement
    for i in range(1, len(data)):
        for j in range(len(data[i])):
            if data[i][j] == 'No':
                table.setStyle(TableStyle([('TEXTCOLOR', (j, i), (j, i), colors.red)]))
            if data[i][j] == 'Yes':
                table.setStyle(TableStyle([('TEXTCOLOR', (j, i), (j, i), colors.green)]))
    return mergedElement

def createSplitTable(df, title, colRatio:list, tableWidth=0.9, customTextCols=[], 
                     tableTextStyle=variableUtils.tableTextStyle, topPadding=12, bottomPadding=12, 
                     cellHighlight=False, headerColor='#9C27B0', titleStyle=variableUtils.subsubheadingStyle):
    
    print(f'Creating split table for {title}')
    
    if df.empty:
        table = Paragraph("No data found", variableUtils.subsubheadingStyle)
        mergedElement = KeepTogether([Paragraph(title, titleStyle), Spacer(1, 6), table, Spacer(1, 12)])
        return mergedElement

    else:
        data = [df.columns.to_list()] + df.values.tolist()

        # Convert custom text columns to Paragraphs
        for i in range(1, len(data)):
            for j in customTextCols:
                data[i][j] = Paragraph(str(data[i][j]), tableTextStyle)

        if colRatio is not None:
            colWidths = [ratio/sum(colRatio) * variableUtils.pageSize[0] * tableWidth/2 for ratio in colRatio]
        else:
            colWidths = [1 for _ in range(len(df.columns))]

        # Split rows
        headerRow = data[0]
        bodyRows = data[1:]
        splitPoint = (len(bodyRows) + 1) // 2  # +1 for safe split if odd number

        leftData = [headerRow] + bodyRows[:splitPoint]
        rightData = [headerRow] + bodyRows[splitPoint:]

        # Create left and right tables
        leftTable = Table(leftData, colWidths=colWidths)
        rightTable = Table(rightData, colWidths=colWidths)

        tableStyle = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(headerColor)),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#FFFFFF')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 14),
            ('BOTTOMPADDING', (0, 0), (-1, -1), bottomPadding),
            ('TOPPADDING', (0, 0), (-1, -1), topPadding),
        ])

        leftTable.setStyle(tableStyle)
        rightTable.setStyle(tableStyle)

        # Now combine left and right tables into one row with two columns
        combinedTable = Table(
            [[leftTable, rightTable]],
            colWidths=[variableUtils.pageSize[0]*tableWidth/2]*2,
            hAlign='CENTER',
                style=[
        ('VALIGN', (0, 0), (-1, -1), 'TOP')  # This line is critical
    ]
        )

    mergedElement = KeepTogether([Paragraph(title, titleStyle), Spacer(1, 6), combinedTable, Spacer(1, 12)])

    # Add cellHighlight if needed
    if not cellHighlight:
        return mergedElement

    # Coloring Yes/No
    for i in range(1, len(leftData)):
        for j in range(len(leftData[i])):
            if isinstance(leftData[i][j], str) and leftData[i][j] == 'No':
                leftTable.setStyle(TableStyle([('TEXTCOLOR', (j, i), (j, i), colors.red)]))
            if isinstance(leftData[i][j], str) and leftData[i][j] == 'Yes':
                leftTable.setStyle(TableStyle([('TEXTCOLOR', (j, i), (j, i), colors.green)]))
    for i in range(1, len(rightData)):
        for j in range(len(rightData[i])):
            if isinstance(rightData[i][j], str) and rightData[i][j] == 'No':
                rightTable.setStyle(TableStyle([('TEXTCOLOR', (j, i), (j, i), colors.red)]))
            if isinstance(rightData[i][j], str) and rightData[i][j] == 'Yes':
                rightTable.setStyle(TableStyle([('TEXTCOLOR', (j, i), (j, i), colors.green)]))

    return mergedElement

def createPlotImage(fig):
        buf = BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight')
        buf.seek(0)
        return buf

def addPlotImage(fig, ratio = None, pageSize = variableUtils.pageSize):
        plotImage = createPlotImage(fig)
        topMargin = variableUtils.topMargin
        bottomMargin = variableUtils.bottomMargin
        leftMargin = variableUtils.leftMargin
        rightMargin = variableUtils.rightMargin
        image = Image(plotImage)
        # print(image.drawWidth, image.drawHeight)
        
        # Resize image to fit within margins
        max_height = pageSize[1] - topMargin - bottomMargin  # Max height for Page
        max_width = pageSize[0] - leftMargin - rightMargin  # Max width for Page
        if ratio is not None:
            max_width = max_width * ratio
            max_height = max_height * ratio
        aspect_ratio = min(max_width / image.drawWidth, max_height / image.drawHeight)
        image.drawWidth *= aspect_ratio
        image.drawHeight *= aspect_ratio
        # print(image.drawWidth, image.drawHeight, aspect_ratio)
        # if idx + 1 < numSubplots:
        #    self.elements.append(PageBreak())
        #self.elements.append(PageBreak())
        plt.close(fig)
        return(image)

# New year functions

def getBannerDrawer( firstline, secondline):
    """
    Returns a function that draws a banner with the specified first and second lines of text.
    The returned function can be used as a callback for the onPage event in ReportLab's SimpleDocTemplate.
    Args:        firstline (str): The text to display on the first line of the banner.
        secondline (str): The text to display on the second line of the banner. 
    Returns: function: A function that takes a canvas and a document as arguments and draws the banner on the canvas.
    """
    def drawBanner(canvas, doc):
        canvas.saveState()

        # Banner layout
        pageWidth, pageHeight = doc.pagesize
        bannerHeight = 132
        canvas.setFillColor(colors.HexColor(variableUtils.uniColor))
        canvas.rect(0, pageHeight - bannerHeight, pageWidth, bannerHeight, fill=1, stroke=0)

        # Text: internal margin from left and top
        textLeftMargin = variableUtils.leftMargin
        topOffset = 72  # Distance from top of banner to first text line
        lineSpacing = 36

        try:
            canvas.setFont("Calibri-Bold", 30)
        except:
            canvas.setFont("Helvetica-Bold", 30)  # Fallback

        canvas.setFillColor(colors.white)
        canvas.drawString(textLeftMargin, pageHeight - topOffset, f"{firstline}")
        try:
            canvas.setFont("Calibri-Bold", 24)
        except:
            canvas.setFont("Helvetica-Bold", 24)  # Fallback        
        
        canvas.drawString(textLeftMargin, pageHeight - topOffset - lineSpacing, f"{secondline}")

        canvas.restoreState()

    return drawBanner

def getmodeArgs(filepath):
    """
    Determines the appropriate mode and if_sheet_exists parameters for pd.ExcelWriter based on whether the file already exists.
    """
    if os.path.exists(filepath):
        mode = 'a'  # append mode for existing files
        if_sheet_exists = 'replace'
    else:
        mode = 'w'  # write mode for new files
        if_sheet_exists = None  # Don't specify if_sheet_exists for new files

    # Create ExcelWriter with appropriate parameters
    writer_kwargs = {
        'engine': 'openpyxl',
        'mode': mode
    }
    
    # Only add if_sheet_exists for append mode
    if mode == 'a':
        writer_kwargs['if_sheet_exists'] = if_sheet_exists
    return writer_kwargs

def runDdl(conn, ddl):
    for stmt in ddl.strip().split(";"):
        if stmt.strip():
            conn.execute(text(stmt))

def readDf(engine, sql, params=None):
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})

def toInt(x):
    """Safely convert to int, defaulting to 0."""
    return int(round(x)) if x is not None else 0

def getWhereStatement(cohort, filters: dict = None):
    """Build a WHERE clause string + params dict from cohort and optional filters."""
    whereClauses = ["cohort = :cohort"]
    params = {"cohort": cohort}
    if filters:
        for key, value in filters.items():
            if isinstance(value, list):
                whereClauses.append(f"{key} IN :{key}")
            elif key.endswith("_min") or key.endswith("_max"):
                continue  # handled specially in callers like getTopItemCodes
            else:
                whereClauses.append(f"{key} = :{key}")
        params.update(filters)
    return " AND ".join(whereClauses), params

def _where(cohort, filters):
    """Shorthand: returns (whereClause, params)."""
    if filters:
        return getWhereStatement(cohort, filters)
    return "cohort = :cohort", {"cohort": cohort}

def autoFitColumns(ws, minWidth=5, maxWidth=30, padding=2):
    """Widen each column to fit its header only."""
    for col in ws.columns:
        headerCell = col[0]
        colLetter = get_column_letter(headerCell.column)
        headerLen = len(str(headerCell.value or ""))
        ws.column_dimensions[colLetter].width = max(minWidth, min(maxWidth, headerLen + padding))


