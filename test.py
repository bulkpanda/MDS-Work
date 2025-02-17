import dash
from dash import html, dcc, Input, Output, dash_table
import dash_bootstrap_components as dbc
import pandas as pd

# Sample data for the table
data = {
    "ID": [1, 2, 3],
    "Name": ["Item 1", "Item 2", "Item 3"]
}
df = pd.DataFrame(data)

# Initialize the app
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

# Layout of the app
app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    html.Div(id='page-content')
])

# Index page layout
index_page = html.Div([
    html.H1("Main Page"),
    dash_table.DataTable(
        id='table',
        columns=[{"name": i, "id": i} for i in df.columns],
        data=df.to_dict('records'),
        row_selectable='single',
        selected_rows=[],
    ),
    html.Div(id='table-container')
])

# Page 1 layout
page_1_layout = html.Div([
    html.H1('Detail Page 1'),
    html.P('This is the detail page for a specific item.'),
    dbc.Button("Go back", href='/')
])

# Page 2 layout
page_2_layout = html.Div([
    html.H1('Detail Page 2'),
    html.P('This is another detail page for a specific item.'),
    dbc.Button("Go back", href='/')
])

# Callback to handle page routing
@app.callback(Output('page-content', 'children'),
              [Input('url', 'pathname')])
def display_page(pathname):
    if pathname == '/page-1':
        return page_1_layout
    elif pathname == '/page-2':
        return page_2_layout
    else:
        return index_page

# Callback to handle table interactions
@app.callback(
    Output('table-container', 'children'),
    Input('table', 'selected_rows')
)
def update_table(selected_rows):
    if selected_rows:
        selected_id = df.iloc[selected_rows[0]]['ID']
        if selected_id % 2 == 0:
            return dcc.Link('Go to Page 2', href='/page-2')
        else:
            return dcc.Link('Go to Page 1', href='/page-1')
    return "Select a row to see more details."

# Run the app
if __name__ == '__main__':
    app.run_server(debug=True)
