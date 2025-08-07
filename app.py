# app.py
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
import os
from dotenv import load_dotenv
from urllib.parse import urlparse  # Nieuwe import

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
# REPLACE THIS WITH A LONG, RANDOM, SECRET KEY!
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'jouw_supergeheime_sleutel_hier')

# Get the database URL from environment variables
DATABASE_URL = os.environ.get('DATABASE_URL')

# Function to get a database connection
def get_db_connection():
    conn = None
    try:
        # Parse the DATABASE_URL
        result = urlparse(DATABASE_URL)

        conn = psycopg2.connect(
            host=result.hostname,
            port=result.port,
            database=result.path[1:],  # Remove the leading '/'
            user=result.username,
            password=result.password,
            client_encoding='UTF8'  # Expliciet de client-encoding instellen
        )
        return conn
    except Exception as e:
        print(f"Fout bij het verbinden met de database: {e}")
        return None


# Function to initialize the database (create table if not exists)
def init_db():
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()

            # SQL query to create the table
            create_table_query = """
                CREATE TABLE IF NOT EXISTS gebruikers (
                    id SERIAL PRIMARY KEY,
                    gebruikersnaam VARCHAR(255) UNIQUE NOT NULL,
                    wachtwoord_hash VARCHAR(255) NOT NULL
                );
            """
            cursor.execute(create_table_query)
            conn.commit()
            print("Gebruikers table checked/created.")

            # Removed the logic to create the 'admin' user,
            # as per your request that a user already exists.

        except Exception as e:
            print(f"Fout bij het initialiseren van de database: {e}")
        finally:
            if conn:  # Ensure conn exists before trying to close
                conn.close()
    else:
        print("Geen databaseverbinding beschikbaar voor initialisatie.")


# Call the init_db function when the application starts
# This ensures the database table is set up
with app.app_context():
    init_db()


# Route for the homepage
@app.route('/')
def home():
    return render_template('home.html')


# Routes for product pages
@app.route('/producten/oorbellen')
def oorbellen():
    return render_template('oorbellen.html')


@app.route('/producten/ringen')
def ringen():
    return render_template('ringen.html')


@app.route('/producten/kettingen')
def kettingen():
    return render_template('kettingen.html')


# Route for the contact page
@app.route('/contact')
def contact():
    return render_template('contact.html')


# Route for the admin panel and login
@app.route('/beheren', methods=['GET', 'POST'])
def beheren():
    # Check if the user is already logged in
    if 'ingelogd' in session and session['ingelogd']:
        # If logged in, show the admin panel
        return render_template('home.html')

    # If it's a POST request (form submitted)
    if request.method == 'POST':
        gebruikersnaam = request.form.get('gebruikersnaam')
        wachtwoord = request.form.get('wachtwoord')

        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                # Get both id and password hash from the database
                cursor.execute("SELECT id, wachtwoord_hash FROM gebruikers WHERE gebruikersnaam = %s", (gebruikersnaam,))
                gebruiker = cursor.fetchone()

                # Check if the user exists and if the password is correct
                if gebruiker and check_password_hash(gebruiker[1], wachtwoord):
                    session['ingelogd'] = True
                    session['gebruikersnaam'] = gebruikersnaam  # Store username in session
                    session['gebruiker_id'] = gebruiker[0]  # Store user id in session
                    flash('Succesvol ingelogd!', 'success')
                    return redirect(url_for('beheren'))

                else:
                    flash('Onjuiste gebruikersnaam of wachtwoord.', 'error')
                    return render_template('login.html')

            except Exception as e:
                print(f"Error during login: {e}")
                flash('Er is een technische fout opgetreden.', 'error')
                return render_template('login.html')
            finally:
                if conn:
                    conn.close()
        else:
            flash('Kan geen verbinding maken met de database. Probeer het later opnieuw.', 'error')
            return render_template('login.html')

    return render_template('login.html')


# Route to log out
@app.route('/uitloggen')
def uitloggen():
    session.pop('ingelogd', None)
    session.pop('gebruikersnaam', None)  # Verwijder de gebruikersnaam uit de sessie
    session.pop('gebruiker_id', None)    # Verwijder het gebruiker_id uit de sessie
    flash('Je bent uitgelogd.', 'info')
    return redirect(url_for('home'))


@app.route('/kettingen/toevoegen', methods=['GET', 'POST'])
def ketting_toevoegen():
    if 'ingelogd' not in session or not session['ingelogd']:
        return redirect(url_for('beheren'))

    if request.method == 'POST':
        # Hier verwerk je het formulier om een ketting toe te voegen
        # Laat me weten welke velden je nodig hebt voor een ketting
        flash('Ketting succesvol toegevoegd!', 'success')
        return redirect(url_for('kettingen'))

    return render_template('ketting_toevoegen.html')


if __name__ == '__main__':
    app.run(debug=True)
