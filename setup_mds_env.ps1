# Set environment name
$envName = "MDS"

# Set Python version (must match installed Python version)
$pythonPath = "python"

# Create the virtual environment
& $pythonPath -m venv $envName

# Activate the environment
& .\$envName\Scripts\activate

# Upgrade pip
pip install --upgrade pip

# Install required packages
pip install pandas numpy matplotlib seaborn openpyxl scikit-learn reportlab pillow

# Print success message
Write-Output "Python virtual environment '$envName' created and packages installed successfully!"
Write-Output "To activate it manually, run: .\$envName\Scripts\activate"
