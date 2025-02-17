import dash
import pandas as pd
from dash import Dash, dcc, html, dash_table, Input, Output, callback, State
import dash_bootstrap_components as dbc
from dash_auth import BasicAuth
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
import plotly.express as px
from plotly.subplots import make_subplots
import plotly.graph_objs as go
from variableUtils import *
from Utils import *
pd.set_option('display.max_columns', None)
folder = 'FullSpreadsheets\CAF+v0.1_December+5,+2024\studentwise data'
fileList = os.listdir(folder)
file = fileList[0]
print(file)
df = pd.read_csv(f'{folder}/{file}')
colnamedict = {col:df.iloc[0][col] for col in df.columns}
df.drop(0, inplace=True)
df.set_index(colResponseId, inplace=True)
procedureCols = df.columns[40:55]
mcCols = df.columns[57:3062]
pecCols = df.columns[3063:3075]

# Data for main table
df = mergeColumns(df, serviceColMerge)
def process_row(row, serviceCols, colClinicChoice, colServiceGeneral):
    allCodes = []
    # Extract codes from the service columns
    for col in serviceCols:
        if col in row:
            allCodes += extractCodes(row[col], row[colClinicChoice])
    
    # Extract general service codes and modifiers
    if colServiceGeneral in row:
        general_codes = extractGeneralServiceCode(row[colServiceGeneral])
        general_codes = [(code, location.upper()) for code, location in general_codes]
        allCodes += general_codes
    
    # Format the final string
    codeString = ', '.join([f"{code} {location}" for code, location in allCodes])
    return codeString

df['Items'] = df.apply(lambda row: process_row(row, serviceCols, colClinicChoice, colServiceGeneral), axis=1)
df['sortdate'] = pd.to_datetime(df[colDate], format='%d-%b-%y')
# df[colDate] = df[colDate].apply(convertDate)
df.sort_values(by='sortdate', inplace=True)
df.drop('sortdate', axis=1, inplace=True)


#===================================================================================================================
# Create components for the Dash app
#===================================================================================================================
# Create a Dash table from the DataFrame
df1 = df[[colDate, colFinished, 'Items']]

df1[colDate] = df1.apply(lambda row: f'[{row[colDate]}](/details/{row.name})', axis=1)  # Modify the colDate column to include internal links with response id
# display(df1.head())
tableLayout = html.Div([
        dash_table.DataTable(
            id='datatable-interactivity',
            columns=[
                {"name": i, "id": i, "presentation": "markdown" if i == colDate else None}
                for i in df1.columns
            ],
            data=df1.to_dict('records'),
            style_data_conditional=[
                {'if': {'row_index': 'odd'},
                 'backgroundColor': 'rgb(248, 248, 248)'}
            ],
            style_header={
                'backgroundColor': 'rgb(230, 230, 230)',
                'fontWeight': 'bold',
                'textAlign': 'center'
            },
            row_selectable='multi',  # Allows multiple rows to be selected
            style_table={'width': '50%', 'margin-left': 'auto', 'margin-right': 'auto'},  # Center the table and set its width
                    style_data={
            'whiteSpace': 'normal',
            'height': 'auto',
            },
            style_cell_conditional=[
            {'if': {'column_id': 'Items'},
             'textAlign': 'left',
             'minWidth': '450px', 'width': '350px', 'maxWidth': '450px'},  # Adjust column width accordingly
             {'if': {'column_id': 'Finished'},
             'textAlign': 'left'
            },
        ],
        style_filter={'textAlign': 'left'},  # Left-align the filter box
        filter_action='native',  # Allow filtering of the table
        )
    ], style={'padding': '20px'},)


# Create rubric graphs time series==============================================================================
rubricQues = df.columns[3067:3071]
print(rubricQues)
df2= df[[colDate, 'Items']+list(rubricQues)]
# df2.reset_index(inplace=True)
df2 = convertRubricScale(df2, rubricQues)
# Mapping the dates to indices
date_indices = {date: idx for idx, date in enumerate(df2['Date'])}
df2['DateIndex'] = df2['Date'].map(date_indices)
df2['DateTime'] = pd.to_datetime(df2['Date']).dt.date
# display(df2.head())
# Create the rubric layout
rubricGraphLayout = html.Div([
        dcc.Graph(
            id='rubric-graph',
            ),
         dcc.RangeSlider(
        id='date-range-slider',
        min=df2['DateIndex'].min(),
        max=df2['DateIndex'].max(),
        value=[df2['DateIndex'].min(), df2['DateIndex'].max()],
        marks={row['DateIndex']: {'label':row[colDate]} for i, (idx, row) in enumerate(df2.iterrows()) if i % 5 == 0},
        step=1,  # one step per date
    )
    ], style={'width': '80%', 'display': 'inline-block', 'padding': '0 20'})

# create the filter
rubricGraphFilter =  html.Div([dcc.Input(
        id='keyword-input',
        type='text',
        placeholder='Enter a keyword to filter...',
        style={
            'margin': '10px', 
            'width': '40%', 
            'height': '40px',  # Increase the height for better visibility
            'fontSize': '18px',  # Larger font size for easier reading
            'lineHeight': '40px',  # Align text vertically in the center
            'borderRadius': '5px',  # Rounded corners
            'border': '1px solid #ccc'  # Add a border with a light grey color
        }
    ),
    dcc.RadioItems(
        id='common-keywords',
        options=[
            {'label': 'SIM', 'value': 'SIM'},
            {'label': 'CLINIC', 'value': 'CLINIC'}
        ],
        style={
            'margin': '10px', 
            'display': 'inline-block', 
            'fontSize': '18px',  # Match the font size with the input
            'lineHeight': '24px'  # Ensure the labels are nicely aligned
        },
        inputStyle={
            'marginRight': '5px',  # Space between radio button and label
            'height': '20px',  # Taller radio buttons
            'width': '20px'  # Wider radio buttons for easier clicking
        })
        ])


# Define a simple modal
def create_modal():
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Detail View")),
            dbc.ModalBody(html.Div([
                html.H4('Additional Graphs and Data Here'),
                dcc.Graph(
                    id='additional-graph',
                    figure={},  # Placeholder for additional graphs
                )
            ])),
            dbc.ModalFooter(
                dbc.Button("Close", id="close-modal", className="ms-auto", n_clicks=0)
            ),
        ],
        id="modal",
        is_open=False,  # Starts closed
    )


# Initialize the Dash app
app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP, 'custom.css'])
app.server.secret_key = 'ShinZemirahWaffleTremble'
auth = BasicAuth(app, {"username": "password"})



# Set up the layout with a table and a dropdown
app.layout = html.Div([
html.H1('Student Report', style={'textAlign': 'center'}),
    tableLayout,
    html.Hr(),
    rubricGraphFilter,
    rubricGraphLayout,
    html.Div(id='last-click-index', style={'display': 'none'}),
    create_modal()
])


@app.callback(
    [Output("modal", "is_open"), Output("last-click-index", "children")],
    [Input("rubric-graph", "clickData"), Input("close-modal", "n_clicks")],
    [State("modal", "is_open"), State("last-click-index", "children")]
)
def toggle_modal(clickData, n_clicks, is_open, last_index):
    ctx = dash.callback_context
    # print("Click data:", clickData)
    if not ctx.triggered:
        print("No trigger")
        return is_open, last_index

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    if trigger_id == "close-modal":
        return False, last_index

    if clickData:
        current_index = clickData['points'][0]['customdata']
        # print(clickData, current_index)
        # print(last_index)
        # if last_index == str(current_index):  # Compare as string to handle `None` initialization
        #     print("Same data clicked again, closing!!!", is_open)
        #     # Toggle modal if same point clicked again
        #     return not is_open, None if is_open else last_index

        # Open the modal with new data if a different point is clicked
        print("New data clicked, opening!!!")
        return True, str(current_index)

    return is_open, last_index  # No change in state

@app.callback(
    Output("additional-graph", "figure"),
    [Input("rubric-graph", "clickData")]
)
def update_additional_graph(clickData):
    if clickData:
        formid = clickData['points'][0]['customdata']
        print(formid)
        items = df.loc[formid]['Items']
        itemList = items.split(', ')
        dfrelevantDict = {}
        for item in itemList:
            code = item.split(' ')[0]
            location = item.split(' ')[1]
            if len(item.split(' ')) > 2:
                # print('More than 2 words')
                tag = ' '.join(item.split(' ')[2:])
            else:
                tag = ''
            print(code, location, tag)
            relevantCols = [col for col in df.columns if code in col and location in col]
            if tag!='':
                relevantCols = [col for col in relevantCols if tag.lower() in col.lower()]
            print(item, relevantCols)
            dfrelevant = df.loc[formid][[colDate]+relevantCols]
            
            # dfrelevant is a pd series
            dfrelevant['#Yes'] = sum([1 for col in relevantCols if dfrelevant[col] == 'Yes'])
            dfrelevant['#No'] = sum([1 for col in relevantCols if dfrelevant[col] == 'No'])
            # dfrelevant['#Yes'] = sum([1 for col in relevantCols if dfrelevant[col] == 'Yes'])
            # dfrelevant['#No'] = dfrelevant
            dfrelevantDict[item] = dfrelevant

        # return go.Figure(, layout={'title': 'MC Graph'})
        fig = make_subplots(rows=len(dfrelevantDict), cols=1, subplot_titles=list(dfrelevantDict.keys()), specs=[[{'type': 'pie'}]] * len(dfrelevantDict))

        for i, (item, dfrelevant) in enumerate(dfrelevantDict.items(), start=1):
            total = dfrelevant['#Yes'] + dfrelevant['#No']
            values = [dfrelevant['#Yes'], dfrelevant['#No']]
            labels = ['Yes', 'No']

            fig.add_trace(
            go.Pie(
                labels=labels,
                values=values,
                name=item,
                textinfo='label+percent',
                texttemplate="%{label}: %{value} (%{percent})",
                hoverinfo="label+percent+name",
            ),
            row=i,
            col=1
            )

        fig.update_layout(
            title_text='MC Graph',
            height=300 * len(dfrelevantDict),  # Adjust the height based on the number of subplots
            margin=dict(t=50, b=50, l=50, r=50),  # Increase the margins to avoid overlap
            annotations=[
            dict(
                text=title,
                # x=0.5,
                # y=1.0,  # Adjust the y position to increase the gap
                xref='paper',
                yref='paper',
                showarrow=False,
                font=dict(size=14)
            ) for title in list(dfrelevantDict.keys())
            ]
        )
        return fig

    return go.Figure()


@app.callback(
    Output('keyword-input', 'value'),
    [Input('common-keywords', 'value')]
)
def update_input(selected_keyword):
    return selected_keyword

@app.callback(
    Output('rubric-graph', 'figure'),
    [Input('date-range-slider', 'value'),
      Input('keyword-input', 'value')]
)
def update_graph(selected_range, keyword):
    # Filter data based on the selected range on the slider
    # Assuming 'selected_range' contains indices or actual date values that are converted beforehand

    filtered_df = df2[(df2['DateTime'] >= df2['DateTime'].iloc[selected_range[0]]) &
                      (df2['DateTime'] <= df2['DateTime'].iloc[selected_range[1]])]
     # Apply keyword filter if a keyword is provided
    if keyword:
        filtered_df = filtered_df[filtered_df['Items'].str.contains(keyword, case=False, na=False)]
    # Number of rubric questions
    num_rubrics = len(rubricQues)

    # Create a subplot with 1 column and 'num_rubrics' rows
    fig = make_subplots(rows=num_rubrics, cols=1, shared_xaxes=True, vertical_spacing=0.1,
                        subplot_titles=rubricQues)

    # Add a scatter plot for each rubric
    for i, rubric in enumerate(rubricQues, start=1):
        thisdf = filtered_df[filtered_df[rubric] != 0]
        fig.add_trace(
            go.Scatter(
                # remove data with 0 score
                
                x=thisdf['DateTime'],
                y=thisdf[rubric],
                mode='lines+markers',
                name=rubric,
                text=thisdf['Items'],  # This will show item details on hover,
                customdata=thisdf.index,  # This will be used to identify the clicked point
                hoverinfo='text+x+y+name',
                        hovertemplate=(
            '<b>Date:</b> %{x|%d-%b-%Y}<br>'  # Format date, adjust formatting string as needed
            '<b>Score:</b> %{y}<br>'           # Display y-value
            '<b>Items:</b> %{text}<br>'      # Display additional text
            '<extra></extra>'                   # Hide the trace name in the tooltip
        )
            ),
            row=i,  # Position of the subplot
            col=1
        )
        # Update y-axis for each subplot to have a range from 0 to 4 with ticks at every integer
        fig.update_yaxes(title_text='Score', range=[0, filtered_df[rubric].max()+1], dtick=1, row=i, col=1)

    # Update the layout of the figure
    fig.update_layout(
        title={
        'text': 'Rubric Scores',
        'y': 0.95,  # You can adjust this to shift the title up or down
        'x': 0.5,  # Center alignment
        'xanchor': 'center',  # Ensures that the title is centered at the specified x position
        'yanchor': 'top',  # Ensures that the title is aligned at the top of its text block
        'font': {
            'family': 'Arial, sans-serif',  # Font family
            'size': 32,  # Font size
            'color': 'black',  # Font color
            
            # 'weight': 'bold'  # Bold font weight
            }
        },
        # xaxis_title='Date',
        yaxis_title='Score',
        height=200 * num_rubrics,  # Adjust the height based on the number of rubrics
        showlegend=False,  # Hide the legend
        # xaxis=dict(

        #     rangeslider=dict(visible=True),
        #     type='date'
        # )
    )

    return fig

# Run the server
if __name__ == '__main__':
    app.run(port = 8050, debug=True)
