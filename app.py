from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import fitz  # PyMuPDF
import os
import re
import asyncio
from datadis import get_token, get_supplies

app = Flask(__name__)
app.secret_key = 'your_secret_key'

login_manager = LoginManager()
login_manager.init_app(app)

class User(UserMixin):
    def __init__(self, id):
        self.id = id

@login_manager.user_loader
def load_user(user_id):
    return User(user_id)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == 'test' and password == 'password':
            user = User(username)
            login_user(user)
            return redirect(url_for('upload'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    supplies_data = None
    error_message = None
    if request.method == 'POST':
        file = request.files['file']
        if file and file.filename.endswith('.pdf'):
            if not os.path.exists('uploads'):
                os.makedirs('uploads')
            file_path = os.path.join('uploads', file.filename)
            file.save(file_path)
            extracted_data = extract_data_from_pdf(file_path)
            token = asyncio.run(authenticate_datadis())
            if token:
                supplies_data = asyncio.run(fetch_supplies_data(token))
                print("Fetched Supplies Data:", supplies_data)  # Debugging line
            else:
                error_message = "Error during authentication. Could not fetch supplies data."
            return render_template('upload.html', extracted_data=extracted_data, supplies_data=supplies_data, error_message=error_message)
    return render_template('upload.html', extracted_data=None, supplies_data=None, error_message=error_message)

async def authenticate_datadis():
    try:
        token = await get_token('B42749481', 'Gestion2024!')
        print("Received Token:", token)  # Debugging line to see the token
        return token
    except Exception as e:
        print(f"Error during authentication: {e}")  # Debugging line to see the error
        return None

async def fetch_supplies_data(token):
    try:
        supplies_data = await get_supplies(token)
        print("Supplies Data:", supplies_data)
        return supplies_data
    except Exception as e:
        print(f"Error fetching supplies data: {e}")
        return []

def extract_data_from_pdf(file_path):
    text = ""
    try:
        with fitz.open(file_path) as pdf:
            for page_num in range(len(pdf)):
                page = pdf.load_page(page_num)
                page_text = page.get_text()
                if page_text:
                    text += page_text + "\n"
                    print(f"Page {page_num + 1} Text: {page_text}")  # Debugging line to see each page's text
                else:
                    print(f"Page {page_num + 1} is empty or text extraction failed.")  # Debugging line
    except Exception as e:
        print(f"Error reading PDF file: {e}")
        return {}

    # Preprocess text: remove extra whitespaces and newlines
    text = ' '.join(text.split())
    print("Extracted Full Text:", text)  # Debugging line to see the full extracted text

    if not text:
        print("No text extracted from the PDF.")
        return {}

    data = {}

    # Refined patterns for common invoice fields
    patterns = {
        'CUPS': [r'CUPS[:\s]*(ES[0-9A-Z]+)'],
        'Consumo total': [r'Consumo total[:\s]*([\d,.]+)\s*kWh', r'Su consumo en el periodo facturado ha sido\s*([\d,.]+)\s*kWh'],
        'Dirección de suministro': [r'Dirección (?:del )?suministro[:\s]*(.+?)(?:\s*Contrato|\s*NIF|\s*CUPS|\s*Importe factura|\s*Número de contrato)'],
        'Número de factura': [r'(?i)n[úu]mero de factura[:\s]*(\S+)'],
        'Fecha de factura': [r'(?i)fecha (?:de )?factura[:\s]*(\d{2}[-/]\d{2}[-/]\d{4})'],
        'Importe factura': [r'(?i)importe (?:de )?factura[:\s]*([\d,.]+ ?€)'],
        'Periodo de facturación': [r'(?i)periodo (?:de )?facturación[:\s]*(\d{2}[-/]\d{2}[-/]\d{4}\s*[-a]\s*\d{2}[-/]\d{2}[-/]\d{4})'],
        'Titular': [r'(?i)titular[:\s]*(.+?)(?:\s*NIF|\s*Dirección|\s*CUPS|\s*Contrato)'],
        'NIF/NIE': [r'(?i)nif[:\s]*(\S+)'],
        'Dirección': [r'(?i)dirección[:\s]*(.+?)(?:\s*Contrato|\s*NIF|\s*CUPS|\s*Importe factura|\s*Número de contrato)'],
        'Contrato': [r'(?i)contrato[:\s]*(\S+)'],
        'Código postal': [r'(?i)código postal[:\s]*(\d{5})'],
        'Provincia': [r'(?i)provincia[:\s]*(\S+)'],
        'Municipio': [r'(?i)municipio[:\s]*(\S+)'],
        'Distribuidora': [r'(?i)nombre de la distribuidora[:\s]*(.+?)(?:\s|$)'],
        'Fecha de inicio del contrato': [r'(?i)fecha de inicio del contrato[:\s]*(\d{4}/\d{2}/\d{2})'],
        'Fecha de fin del contrato': [r'(?i)fecha de fin del contrato[:\s]*(\d{4}/\d{2}/\d{2})'],
        'Tipo de punto de medida': [r'(?i)tipo de punto de medida[:\s]*(\d+)'],
        'Código de distribuidora': [r'(?i)código de distribuidora[:\s]*(\d+)'],
        'Alquiler del contador': [r'Alquiler del contador[:\s]*([\d,.]+ ?€)'],
        'Otros conceptos': [r'Otros conceptos[:\s]*([\d,.]+ ?€)'],
        'Impuesto electricidad': [r'Impuesto Electricidad[:\s]*([\d,.]+ ?€)'],
        'IVA': [r'IVA[:\s]*([\d,.]+ ?€)'],
        'Total factura': [r'Total factura[:\s]*([\d,.]+ ?€)'],
        'Potencia contratada P1': [r'Pot\. P1[:\s]*([\d,.]+ kW x \d+ días x [\d,.]+ Eur/kW y día)'],
        'Potencia contratada P2': [r'Pot\. P2[:\s]*([\d,.]+ kW x \d+ días x [\d,.]+ Eur/kW y día)'],
        'Potencia contratada P3': [r'Pot\. P3[:\s]*([\d,.]+ kW x \d+ días x [\d,.]+ Eur/kW y día)'],
        'Potencia contratada P4': [r'Pot\. P4[:\s]*([\d,.]+ kW x \d+ días x [\d,.]+ Eur/kW y día)'],
        'Potencia contratada P5': [r'Pot\. P5[:\s]*([\d,.]+ kW x \d+ días x [\d,.]+ Eur/kW y día)'],
        'Potencia contratada P6': [r'Pot\. P6[:\s]*([\d,.]+ kW x \d+ días x [\d,.]+ Eur/kW y día)'],
        'Importe Total': [r'Importe Total[:\s]*([\d,.]+)\s*€'],
        'Fecha fin del contrato de suministro': [r'Fecha fin del contrato de suministro[:\s]*(\d{2}/\d{2}/\d{4})'],
        'Consumo P1': [r'Consumo\s+P1\s*:\s*([\d,.]+)\s*kWh'],
        'Consumo P2': [r'Consumo\s+P2\s*:\s*([\d,.]+)\s*kWh'],
        'Consumo P3': [r'Consumo\s+P3\s*:\s*([\d,.]+)\s*kWh'],
        'Precio total P1': [r'P1\s*:\s*[\d,.]+\s*€/kWh\s*\+\s*[\d,.]+\s*€/kWh\s*\+\s*[\d,.]+\s*€/kWh\s*=\s*([\d,.]+)\s*€'],
        'Precio total P2': [r'P2\s*:\s*[\d,.]+\s*€/kWh\s*\+\s*[\d,.]+\s*€/kWh\s*\+\s*[\d,.]+\s*€/kWh\s*=\s*([\d,.]+)\s*€'],
        'Precio total P3': [r'P3\s*:\s*[\d,.]+\s*€/kWh\s*\+\s*[\d,.]+\s*€/kWh\s*\+\s*[\d,.]+\s*€/kWh\s*=\s*([\d,.]+)\s*€'],
        'Importe total P1': [r'P1\s*:\s*[\d,.]+\s*€/kWh\s*\+\s*[\d,.]+\s*€/kWh\s*\+\s*[\d,.]+\s*€/kWh\s*=\s*[\d,.]+\s*€\s*x\s*[\d,.]+\s*kWh\s*=\s*([\d,.]+)\s*€'],
        'Importe total P2': [r'P2\s*:\s*[\d,.]+\s*€/kWh\s*\+\s*[\d,.]+\s*€/kWh\s*\+\s*[\d,.]+\s*€/kWh\s*=\s*[\d,.]+\s*€\s*x\s*[\d,.]+\s*kWh\s*=\s*([\d,.]+)\s*€'],
        'Importe total P3': [r'P3\s*:\s*[\d,.]+\s*€/kWh\s*\+\s*[\d,.]+\s*€/kWh\s*\+\s*[\d,.]+\s*€/kWh\s*=\s*[\d,.]+\s*€\s*x\s*[\d,.]+\s*kWh\s*=\s*([\d,.]+)\s*€'],
        'Impuesto electricidad': [r'Impuesto\s*electricidad\s*[:\s]*([\d,.]+)\s*€'],
        'Alquiler Equipo medida': [r'Alquiler\s*Equipo\s*medida\s*[:\s]*([\d,.]+)\s*€'],
        'Bono social': [r'Bono\s*social\s*[:\s]*([\d,.]+)\s*€'],
        'IVA Reducido': [r'IVA\s*Reducido\s*[:\s]*([\d,.]+)\s*€'],
        'IVA General': [r'IVA\s*[:\s]*([\d,.]+)\s*€'],
        'Total electricidad': [r'Total electricidad\s*([\d,.]+)\s*€'],
        'Total tasas e impuestos': [r'Total tasas e impuestos\s*([\d,.]+)\s*€'],
        'Importe total electricidad': [r'Importe total electricidad\s*([\d,.]+)\s*€']
    }

    # Extracting data using patterns
    for key, patterns_list in patterns.items():
        for pattern in patterns_list:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                data[key] = match.group(1)
                break
        if key not in data:
            print(f"No match found for {key} with patterns: {patterns_list}")  # Debugging line

    print("Data Dictionary:", data)  # Debugging line
    return data

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        if file and file.filename.endswith('.pdf'):
            file_path = os.path.join('uploads', file.filename)
            file.save(file_path)
            extracted_data = extract_data_from_pdf(file_path)
            return render_template('upload.html', extracted_data=extracted_data)
    return render_template('upload.html')

if __name__ == "__main__":
    app.run(debug=True)


