import secrets

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import DictCursor
import os
from dotenv import load_dotenv
from urllib.parse import urlparse
from PIL import Image
import io
import secrets

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
        result = urlparse(DATABASE_URL)
        conn = psycopg2.connect(
            host=result.hostname,
            port=result.port,
            database=result.path[1:],
            user=result.username,
            password=result.password,
            client_encoding='UTF8',
            cursor_factory=DictCursor  # Voeg dit toe
        )
        return conn
    except Exception as e:
        print(f"Fout bij verbinden met database: {e}")
        return None


def save_image(image_file, target_size=(800, 800), quality=85):
    """Sla afbeelding op met correcte oriëntatie en compressie"""
    if not image_file:
        return None

    filename = secrets.token_hex(8) + ".jpg"
    upload_dir = os.path.join('static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, filename)

    try:
        img = Image.open(image_file.stream)

        # Corrigeer EXIF rotatie
        if hasattr(img, '_getexif'):
            exif = img._getexif()
            if exif:
                orientation = exif.get(0x0112)
                if orientation:
                    if orientation == 3:
                        img = img.rotate(180, expand=True)
                    elif orientation == 6:
                        img = img.rotate(270, expand=True)
                    elif orientation == 8:
                        img = img.rotate(90, expand=True)

        # Converteer naar RGB indien nodig
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')

        # Behoud aspect ratio bij resizen
        img.thumbnail(target_size, Image.LANCZOS)

        # Opslaan met compressie
        img.save(filepath, 'JPEG', quality=quality, optimize=True)
        return filename

    except Exception as e:
        print(f"Fout bij verwerken afbeelding: {e}")
        return None


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
    conn = get_db_connection()
    kettingen_lijst = []
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)  # <-- Dit toevoegen

            # Stap 1: Haal alle kettingen op
            cursor.execute("SELECT * FROM kettingen ORDER BY gemaakt_op DESC")
            kettingen_db = cursor.fetchall()

            # Stap 2: Voor elke ketting, haal de kleurvarianten op
            for ketting in kettingen_db:
                cursor.execute("SELECT * FROM ketting_kleuren WHERE ketting_id = %s ORDER BY id", (ketting['id'],))
                kleuren = cursor.fetchall()

                # Voeg de kleurenlijst toe aan de ketting-dict
                ketting_dict = dict(ketting)
                ketting_dict['kleuren'] = kleuren
                kettingen_lijst.append(ketting_dict)

            return render_template('kettingen.html', kettingen=kettingen_lijst)
        except Exception as e:
            print(f"Fout bij ophalen kettingen: {e}")
            return render_template('kettingen.html', kettingen=[])
        finally:
            if conn:
                conn.close()
    return render_template('kettingen.html', kettingen=[])


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
                cursor.execute("SELECT id, wachtwoord_hash FROM gebruikers WHERE gebruikersnaam = %s",
                               (gebruikersnaam,))
                gebruiker = cursor.fetchone()

                # Check if the user exists and if the password is correct
                if gebruiker and check_password_hash(gebruiker[1], wachtwoord):
                    session['ingelogd'] = True
                    session['gebruikersnaam'] = gebruikersnaam  # Store username in session
                    session['gebruiker_id'] = gebruiker[0]  # Store user id in session
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
    session.pop('gebruiker_id', None)  # Verwijder het gebruiker_id uit de sessie
    return redirect(url_for('home'))


@app.route('/profiel')
def profiel():
    if 'ingelogd' not in session or not session['ingelogd']:
        return redirect(url_for('beheren'))
    return render_template('profiel.html')


@app.route('/profiel/gebruikersnaam/bewerken', methods=['POST'])
def profiel_gebruikersnaam_bewerken():
    if 'ingelogd' not in session or not session['ingelogd']:
        return jsonify({'message': 'Niet ingelogd', 'category': 'error'})

    conn = get_db_connection()
    if not conn:
        return jsonify({'message': 'Databaseverbinding mislukt', 'category': 'error'})

    nieuwe_gebruikersnaam = request.form.get('gebruikersnaam')

    if not nieuwe_gebruikersnaam or nieuwe_gebruikersnaam == session['gebruikersnaam']:
        return jsonify({'message': 'Geen geldige gebruikersnaam opgegeven', 'category': 'error'})

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM gebruikers WHERE gebruikersnaam = %s AND id != %s",
                       (nieuwe_gebruikersnaam, session['gebruiker_id']))
        if cursor.fetchone():
            return jsonify({'message': 'Deze gebruikersnaam is al in gebruik', 'category': 'error'})
        else:
            cursor.execute("UPDATE gebruikers SET gebruikersnaam = %s WHERE id = %s",
                           (nieuwe_gebruikersnaam, session['gebruiker_id']))
            conn.commit()
            session['gebruikersnaam'] = nieuwe_gebruikersnaam
            return jsonify({'message': 'Gebruikersnaam succesvol aangepast', 'category': 'success',
                            'new_username': nieuwe_gebruikersnaam})

    except Exception as e:
        conn.rollback()
        print(f"Fout bij bijwerken gebruikersnaam: {e}")
        return jsonify(
            {'message': 'Er is een fout opgetreden bij het bijwerken van je gebruikersnaam', 'category': 'error'})
    finally:
        if conn:
            conn.close()


# Route voor het bewerken van het wachtwoord
@app.route('/profiel/wachtwoord/bewerken', methods=['POST'])
def profiel_wachtwoord_bewerken():
    if 'ingelogd' not in session or not session['ingelogd']:
        return jsonify({'message': 'Niet ingelogd', 'category': 'error'})

    conn = get_db_connection()
    if not conn:
        return jsonify({'message': 'Databaseverbinding mislukt', 'category': 'error'})

    oud_wachtwoord = request.form.get('oud_wachtwoord')
    nieuw_wachtwoord = request.form.get('nieuw_wachtwoord')
    bevestig_wachtwoord = request.form.get('bevestig_wachtwoord')

    if not oud_wachtwoord or not nieuw_wachtwoord or not bevestig_wachtwoord:
        return jsonify({'message': 'Vul alle wachtwoordvelden in', 'category': 'error'})

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT wachtwoord_hash FROM gebruikers WHERE id = %s",
                       (session['gebruiker_id'],))
        result = cursor.fetchone()

        if not result or not check_password_hash(result[0], oud_wachtwoord):
            return jsonify({'message': 'Oud wachtwoord is incorrect', 'category': 'error'})

        if nieuw_wachtwoord != bevestig_wachtwoord:
            return jsonify({'message': 'Nieuwe wachtwoorden komen niet overeen', 'category': 'error'})

        if nieuw_wachtwoord == oud_wachtwoord:
            return jsonify({'message': 'Nieuw wachtwoord mag niet hetzelfde zijn als het oude', 'category': 'error'})

        nieuwe_hash = generate_password_hash(nieuw_wachtwoord)
        cursor.execute("UPDATE gebruikers SET wachtwoord_hash = %s WHERE id = %s",
                       (nieuwe_hash, session['gebruiker_id']))
        conn.commit()
        return jsonify({'message': 'Wachtwoord succesvol aangepast', 'category': 'success'})

    except Exception as e:
        conn.rollback()
        print(f"Fout bij bijwerken wachtwoord: {e}")
        return jsonify(
            {'message': 'Er is een fout opgetreden bij het bijwerken van je wachtwoord', 'category': 'error'})
    finally:
        if conn:
            conn.close()


@app.route('/producten/kettingen/<int:ketting_id>')
def ketting_detail(ketting_id):
    conn = get_db_connection()
    if not conn:
        flash('Databaseverbinding mislukt', 'error')
        return redirect(url_for('kettingen'))

    try:
        cursor = conn.cursor(cursor_factory=DictCursor)
        cursor.execute("SELECT * FROM kettingen WHERE id = %s", (ketting_id,))
        ketting = cursor.fetchone()

        if not ketting:
            flash('Ketting niet gevonden', 'error')
            return redirect(url_for('kettingen'))

        cursor.execute("SELECT * FROM ketting_kleuren WHERE ketting_id = %s ORDER BY id", (ketting_id,))
        kleuren = cursor.fetchall()

        return render_template('ketting_detail.html',
                               ketting=ketting,
                               kleuren=kleuren)
    except Exception as e:
        print(f"FOUT bij ophalen ketting details: {str(e)}")
        flash('Databasefout bij ophalen ketting details', 'error')
        return redirect(url_for('kettingen'))
    finally:
        if conn:
            conn.close()

# Nieuwe route voor het toevoegen van kettingen
@app.route('/kettingen/toevoegen', methods=['GET', 'POST'])
def ketting_toevoegen():
    if 'ingelogd' not in session or not session['ingelogd']:
        return redirect(url_for('beheren'))

    if request.method == 'POST':
        try:
            naam = request.form.get('naam')
            beschrijving = request.form.get('beschrijving')
            prijs = request.form.get('prijs')

            kleur_namen = request.form.getlist('kleur_naam[]')
            kleur_fotos = request.files.getlist('kleur_foto[]')
            kleur_hover_fotos = request.files.getlist('kleur_hover_foto[]')

            if not kleur_namen or not kleur_namen[0]:
                flash('Vul ten minste één kleurvariant in.', 'error')
                return redirect(url_for('ketting_toevoegen'))

            conn = get_db_connection()
            if not conn:
                flash('Databaseverbinding mislukt', 'error')
                return redirect(url_for('ketting_toevoegen'))

            try:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO kettingen (naam, beschrijving, prijs) VALUES (%s, %s, %s) RETURNING id",
                    (naam, beschrijving, float(prijs))
                )
                ketting_id = cursor.fetchone()[0]

                for i in range(len(kleur_namen)):
                    if kleur_namen[i] and kleur_fotos[i] and kleur_hover_fotos[i]:
                        kleur_foto_filename = save_image(kleur_fotos[i])
                        kleur_hover_foto_filename = save_image(kleur_hover_fotos[i])
                        if kleur_foto_filename and kleur_hover_foto_filename:
                            cursor.execute(
                                "INSERT INTO ketting_kleuren (ketting_id, kleur_naam, foto, hover_foto) VALUES (%s, %s, %s, %s)",
                                (ketting_id, kleur_namen[i], kleur_foto_filename, kleur_hover_foto_filename)
                            )
                        else:
                            raise Exception("Afbeeldingen voor een kleurvariant konden niet worden opgeslagen.")
                    else:
                        flash('Vul alle velden voor de kleurvariant in.', 'error')
                        conn.rollback()
                        return redirect(url_for('ketting_toevoegen'))

                conn.commit()
                flash('Ketting succesvol toegevoegd!', 'success')
                return redirect(url_for('kettingen'))

            except Exception as e:
                conn.rollback()
                print(f"Databasefout: {e}")
                flash('Er is een databasefout opgetreden', 'error')
                return redirect(url_for('ketting_toevoegen'))
            finally:
                if conn:
                    conn.close()

        except Exception as e:
            print(f"Fout bij toevoegen ketting: {e}")
            flash('Er is een fout opgetreden bij het toevoegen van de ketting', 'error')
            return redirect(url_for('ketting_toevoegen'))

    return render_template('ketting_toevoegen.html')


# Nieuwe route voor het bewerken van kettingen
@app.route('/kettingen/bewerken/<int:ketting_id>', methods=['GET', 'POST'])
def ketting_bewerken(ketting_id):
    if 'ingelogd' not in session or not session['ingelogd']:
        return redirect(url_for('beheren'))

    # GET Request - Toon bewerkformulier
    if request.method == 'GET':
        conn = get_db_connection()
        if not conn:
            flash('Databaseverbinding mislukt', 'error')
            return redirect(url_for('kettingen'))

        try:
            cursor = conn.cursor(cursor_factory=DictCursor)
            cursor.execute("SELECT * FROM kettingen WHERE id = %s", (ketting_id,))
            ketting = cursor.fetchone()

            if not ketting:
                flash('Ketting niet gevonden', 'error')
                return redirect(url_for('kettingen'))

            cursor.execute("SELECT * FROM ketting_kleuren WHERE ketting_id = %s ORDER BY id", (ketting_id,))
            kleuren = cursor.fetchall()

            return render_template('ketting_bewerken.html',
                                   ketting=ketting,
                                   kleuren=kleuren)
        except Exception as e:
            print(f"FOUT bij ophalen ketting: {str(e)}")
            flash('Databasefout bij ophalen ketting', 'error')
            return redirect(url_for('kettingen'))
        finally:
            if conn:
                conn.close()

    # POST Request - Verwerk formulier
    if request.method == 'POST':
        print("POST request ontvangen voor ketting bewerken")  # Debug log

        # Valideer vereiste velden
        naam = request.form.get('naam')
        beschrijving = request.form.get('beschrijving')
        prijs = request.form.get('prijs')

        if not all([naam, beschrijving, prijs]):
            flash('Vul alle verplichte velden in', 'error')
            return redirect(url_for('ketting_bewerken', ketting_id=ketting_id))

        try:
            prijs = float(prijs)
        except ValueError:
            flash('Ongeldige prijs', 'error')
            return redirect(url_for('ketting_bewerken', ketting_id=ketting_id))

        # Verwerk kleurvarianten
        kleur_namen = request.form.getlist('kleur_naam[]')
        kleur_fotos = request.files.getlist('kleur_foto[]')
        kleur_hover_fotos = request.files.getlist('kleur_hover_foto[]')

        print(f"Aantal kleurvarianten: {len(kleur_namen)}")  # Debug log

        if not kleur_namen or not any(kleur_namen):
            flash('Voeg minimaal één kleurvariant toe', 'error')
            return redirect(url_for('ketting_bewerken', ketting_id=ketting_id))

        conn = get_db_connection()
        if not conn:
            flash('Databaseverbinding mislukt', 'error')
            return redirect(url_for('ketting_bewerken', ketting_id=ketting_id))

        try:
            cursor = conn.cursor()

            # Update ketting basisinformatie
            cursor.execute(
                "UPDATE kettingen SET naam = %s, beschrijving = %s, prijs = %s WHERE id = %s",
                (naam, beschrijving, prijs, ketting_id)
            )
            print("Ketting basisinformatie bijgewerkt")  # Debug log

            # Verwijder bestaande kleuren
            cursor.execute("DELETE FROM ketting_kleuren WHERE ketting_id = %s", (ketting_id,))
            print("Oude kleurvarianten verwijderd")  # Debug log

            # Voeg nieuwe kleurvarianten toe
            for i, kleur_naam in enumerate(kleur_namen):
                if not kleur_naam:
                    continue  # Sla lege kleurvarianten over

                print(f"Verwerken kleurvariant {i + 1}: {kleur_naam}")  # Debug log

                # Verwerk afbeeldingen
                oude_foto = request.form.get(f'oude_foto_{i}', '')
                oude_hover_foto = request.form.get(f'oude_hover_foto_{i}', '')

                # Behandel kleur foto
                kleur_foto_bestand = kleur_fotos[i] if i < len(kleur_fotos) else None
                kleur_foto = oude_foto
                if kleur_foto_bestand and kleur_foto_bestand.filename:
                    kleur_foto = save_image(kleur_foto_bestand)
                    if not kleur_foto:
                        raise Exception(f"Kon kleurfoto {i + 1} niet opslaan")

                # Behandel hover foto
                kleur_hover_bestand = kleur_hover_fotos[i] if i < len(kleur_hover_fotos) else None
                kleur_hover_foto = oude_hover_foto
                if kleur_hover_bestand and kleur_hover_bestand.filename:
                    kleur_hover_foto = save_image(kleur_hover_bestand)
                    if not kleur_hover_foto:
                        raise Exception(f"Kon hoverfoto {i + 1} niet opslaan")

                # Voeg kleurvariant toe aan database
                cursor.execute(
                    "INSERT INTO ketting_kleuren (ketting_id, kleur_naam, foto, hover_foto) "
                    "VALUES (%s, %s, %s, %s)",
                    (ketting_id, kleur_naam, kleur_foto, kleur_hover_foto)
                )
                print(f"Kleurvariant {i + 1} toegevoegd aan database")  # Debug log

            conn.commit()
            print("Wijzigingen succesvol opgeslagen in database")  # Debug log
            flash('Ketting succesvol bijgewerkt!', 'success')
            return redirect(url_for('kettingen'))

        except Exception as e:
            conn.rollback()
            print(f"FOUT tijdens bewerken ketting: {str(e)}")  # Debug log
            flash(f'Fout bij bijwerken ketting: {str(e)}', 'error')
            return redirect(url_for('ketting_bewerken', ketting_id=ketting_id))
        finally:
            if conn:
                conn.close()


@app.route('/kettingen/verwijderen/<int:ketting_id>', methods=['POST'])
def ketting_verwijderen(ketting_id):
    if 'ingelogd' not in session or not session['ingelogd']:
        return redirect(url_for('beheren'))

    conn = get_db_connection()
    if not conn:
        flash('Databaseverbinding mislukt', 'error')
        return redirect(url_for('kettingen'))

    try:
        cursor = conn.cursor()

        # Eerst de kleurvarianten verwijderen (vanwege foreign key constraint)
        cursor.execute("DELETE FROM ketting_kleuren WHERE ketting_id = %s", (ketting_id,))

        # Dan de ketting zelf verwijderen
        cursor.execute("DELETE FROM kettingen WHERE id = %s", (ketting_id,))

        conn.commit()
        flash('Ketting succesvol verwijderd!', 'success')
    except Exception as e:
        conn.rollback()
        print(f"FOUT bij verwijderen ketting: {str(e)}")
        flash('Er is een fout opgetreden bij het verwijderen van de ketting', 'error')
    finally:
        if conn:
            conn.close()

    return redirect(url_for('kettingen'))

if __name__ == '__main__':
    app.run(debug=True)