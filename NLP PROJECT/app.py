import os
import logging
from io import BytesIO
from flask import Flask, render_template, request, send_file, session
import google.generativeai as genai
import requests
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import folium

# Set up logging
logging.basicConfig(level=logging.INFO)

# Set up Gemini API
os.environ['GOOGLE_API_KEY'] = 'AIzaSyD3zRlPaUxBEU3e1cujoOTFGRHKsjSF07c'
genai.configure(api_key=os.environ['GOOGLE_API_KEY'])

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Necessary for session storage

# Function to get coordinates
def get_coordinates(address):
    url = f"https://nominatim.openstreetmap.org/search?q={address}&format=json&limit=1"
    headers = {"User-Agent": "HealthcareAssistant/1.0"}
    response = requests.get(url, headers=headers)
    data = response.json()
    if data:
        return float(data[0]['lat']), float(data[0]['lon'])
    return None, None

# Function to find nearby places
def find_nearby_places(lat, lon, place_type, radius=5000):
    overpass_url = "http://overpass-api.de/api/interpreter"
    overpass_query = f"""
    [out:json];
    (
      node["amenity"="{place_type}"](around:{radius},{lat},{lon});
      way["amenity"="{place_type}"](around:{radius},{lat},{lon});
      relation["amenity"="{place_type}"](around:{radius},{lat},{lon});
    );
    out center;
    """
    response = requests.get(overpass_url, params={'data': overpass_query})
    data = response.json()
    return data['elements']

# Query healthcare assistant
def query_healthcare_assistant(symptoms):
    prompt = f"""Given the symptoms '{symptoms}', list possible health conditions, recommended medicines, and advice in the following format:

    Conditions:
    - Condition 1
    - Condition 2
    ...

    Medicines:
    - Medicine 1
    - Medicine 2
    ...

    Advice:
    - Advice 1
    - Advice 2
    ...
    """
    model = genai.GenerativeModel('gemini-pro')
    try:
        response = model.generate_content(prompt)
        if response and response.text:
            # Parsing the model's response based on expected format
            sections = response.text.strip().split('\n\n')
            if len(sections) >= 3:
                conditions = [line[2:].strip() for line in sections[0].splitlines() if line.startswith("-")]
                medicines = [line[2:].strip() for line in sections[1].splitlines() if line.startswith("-")]
                advice = [line[2:].strip() for line in sections[2].splitlines() if line.startswith("-")]

                # Truncate to top 5 items each
                return {
                    "conditions": conditions[:5],
                    "medicines": medicines[:5],
                    "advice": advice[:5]
                }
        logging.warning("Unexpected response format or empty response from healthcare assistant.")
        return {"conditions": [], "medicines": [], "advice": []}
    except Exception as e:
        logging.error(f"Error in query_healthcare_assistant: {e}")
        return {"conditions": [], "medicines": [], "advice": []}

# PDF report creation
def create_pdf(report):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.drawString(100, 750, "Healthcare Report")
    y = 730
    for key, items in report.items():
        c.drawString(100, y, f"{key.capitalize()}:")
        y -= 20
        for item in items:
            text = c.beginText(120, y)
            text.textLines(item)
            c.drawText(text)
            y -= 15
        y -= 10
    c.save()
    buffer.seek(0)
    return buffer


from flask import Flask, render_template

app = Flask(__name__, static_folder='assets')
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    symptoms = request.form['symptoms']
    address = request.form['address']

    if symptoms and address:
        report = query_healthcare_assistant(symptoms)
        lat, lon = get_coordinates(address)
        
        if lat and lon:
            hospitals = find_nearby_places(lat, lon, "hospital")
            pharmacies = find_nearby_places(lat, lon, "pharmacy")

            # Generate map
            m = folium.Map(location=[lat, lon], zoom_start=13)
            folium.Marker([lat, lon], popup="Your Location", icon=folium.Icon(color='red')).add_to(m)
            
            for hospital in hospitals:
                if 'lat' in hospital:
                    folium.Marker(
                        [hospital['lat'], hospital['lon']],
                        popup=hospital.get('tags', {}).get('name', 'Hospital'),
                        icon=folium.Icon(color='blue')
                    ).add_to(m)

            for pharmacy in pharmacies:
                if 'lat' in pharmacy:
                    folium.Marker(
                        [pharmacy['lat'], pharmacy['lon']],
                        popup=pharmacy.get('tags', {}).get('name', 'Pharmacy'),
                        icon=folium.Icon(color='green')
                    ).add_to(m)
            
            map_html = m._repr_html_()
            pdf_buffer = create_pdf(report)

            # Store pdf_buffer in session for download
            session['pdf_buffer'] = pdf_buffer.getvalue()

            return render_template(
                'results.html', 
                conditions=report['conditions'],
                medicines=report['medicines'],
                advice=report['advice'],
                map_html=map_html,
                hospitals=hospitals[:5],  # Show top 5 results
                pharmacies=pharmacies[:5]  # Show top 5 results
            )
        else:
            return render_template('index.html', error="Unable to find coordinates for the given address. Please try again.")
    else:
        return render_template('index.html', error="Please enter both your symptoms and location.")

@app.route('/download')
def download():
    if 'pdf_buffer' in session:
        pdf_buffer = BytesIO(session['pdf_buffer'])
        return send_file(pdf_buffer, as_attachment=True, download_name="healthcare_report.pdf", mimetype="application/pdf")
    return "Error: No PDF available to download."

if __name__ == '__main__':
    app.run(debug=True)
