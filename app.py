# app.py
from flask import Flask, render_template

app = Flask(__name__)

# Route voor de homepagina
@app.route('/')
def home():
    return render_template('home.html')

# Routes voor de productpagina's
@app.route('/producten/oorbellen')
def oorbellen():
    return render_template('oorbellen.html')

@app.route('/producten/ringen')
def ringen():
    return render_template('ringen.html')

@app.route('/producten/kettingen')
def kettingen():
    return render_template('kettingen.html')

# Route voor de contactpagina
@app.route('/contact')
def contact():
    return render_template('contact.html')

if __name__ == '__main__':
    # Zorg ervoor dat de app draait in debug-modus voor ontwikkeling
    app.run(debug=True)
