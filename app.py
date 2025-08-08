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

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'jouw_supergeheime_sleutel_hier')

# Get the database URL from environment variables
DATABASE_URL = os.environ.get('DATABASE_URL')


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
            cursor_factory=DictCursor
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


# Helper functies
def get_categorie_naam(categorie_id):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT naam FROM categorieen WHERE id = %s", (categorie_id,))
            result = cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            print(f"Fout bij ophalen categorie naam: {e}")
            return None
        finally:
            if conn:
                conn.close()
    return None


# Routes
@app.route('/')
def home():
    return render_template('home.html')


@app.route('/producten/<categorie>')
def producten_per_categorie(categorie):
    conn = get_db_connection()
    producten_lijst = []
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=DictCursor)

            # Controleer of categorie bestaat
            cursor.execute("SELECT id FROM categorieen WHERE naam ILIKE %s", (categorie,))
            categorie_result = cursor.fetchone()

            if not categorie_result:
                flash(f'Categorie "{categorie}" niet gevonden', 'error')
                return redirect(url_for('home'))

            categorie_id = categorie_result['id']

            # Haal producten op met JOIN op categorieen voor betrouwbaarheid
            cursor.execute("""
                SELECT p.*, c.naam AS categorie_naam 
                FROM producten p
                JOIN categorieen c ON p.categorie_id = c.id
                WHERE c.id = %s 
                ORDER BY p.gemaakt_op DESC
            """, (categorie_id,))
            producten_db = cursor.fetchall()

            # Voor elk product de kleuren ophalen
            for product in producten_db:
                cursor.execute("""
                    SELECT * FROM product_kleuren 
                    WHERE product_id = %s 
                    ORDER BY id
                """, (product['id'],))
                kleuren = cursor.fetchall()

                product_dict = dict(product)
                product_dict['kleuren'] = kleuren
                producten_lijst.append(product_dict)

            return render_template('producten.html',
                                   producten=producten_lijst,
                                   categorie=categorie)

        except Exception as e:
            print(f"Database error: {e}")
            flash('Er is een fout opgetreden bij het ophalen van producten', 'error')
            return redirect(url_for('home'))
        finally:
            if conn:
                conn.close()

    flash('Kon geen verbinding maken met de database', 'error')
    return redirect(url_for('home'))


@app.route('/producten/<categorie>/<int:product_id>')
def product_detail(categorie, product_id):
    conn = get_db_connection()
    if not conn:
        flash('Databaseverbinding mislukt', 'error')
        return redirect(url_for('producten_per_categorie', categorie=categorie))

    try:
        cursor = conn.cursor(cursor_factory=DictCursor)
        cursor.execute("SELECT * FROM producten WHERE id = %s", (product_id,))
        product = cursor.fetchone()

        if not product:
            flash('Product niet gevonden', 'error')
            return redirect(url_for('producten_per_categorie', categorie=categorie))

        cursor.execute("SELECT * FROM product_kleuren WHERE product_id = %s ORDER BY id", (product_id,))
        kleuren = cursor.fetchall()

        return render_template('product_detail.html',
                               product=product,
                               kleuren=kleuren,
                               categorie=categorie)
    except Exception as e:
        print(f"FOUT bij ophalen product details: {str(e)}")
        flash('Databasefout bij ophalen product details', 'error')
        return redirect(url_for('producten_per_categorie', categorie=categorie))
    finally:
        if conn:
            conn.close()


@app.route('/producten/toevoegen', methods=['GET', 'POST'])
def product_toevoegen():
    if 'ingelogd' not in session or not session['ingelogd']:
        return redirect(url_for('beheren'))

    # Clear old flash messages
    session.pop('_flashes', None)

    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM categorieen")
            categorieen = cursor.fetchall()
        except Exception as e:
            print(f"Fout bij ophalen categorieën: {e}")
            categorieen = []
        finally:
            if conn:
                conn.close()
    else:
        categorieen = []

    if request.method == 'POST':
        try:
            naam = request.form.get('naam')
            beschrijving = request.form.get('beschrijving')
            prijs = request.form.get('prijs')
            categorie_id = request.form.get('categorie_id')

            # Filter lege kleurvarianten eruit
            kleur_namen = []
            kleur_fotos = []
            kleur_hover_fotos = []

            for i, kleur_naam in enumerate(request.form.getlist('kleur_naam[]')):
                if kleur_naam.strip():  # Alleen niet-lege namen toevoegen
                    kleur_foto = request.files.getlist('kleur_foto[]')[i]
                    kleur_hover_foto = request.files.getlist('kleur_hover_foto[]')[i]

                    # Controleer of bestanden zijn geüpload
                    if kleur_foto and kleur_foto.filename and kleur_hover_foto and kleur_hover_foto.filename:
                        kleur_namen.append(kleur_naam)
                        kleur_fotos.append(kleur_foto)
                        kleur_hover_fotos.append(kleur_hover_foto)

            if not kleur_namen:
                flash('Vul ten minste één volledige kleurvariant in.', 'error')
                return redirect(url_for('product_toevoegen'))

            conn = get_db_connection()
            if not conn:
                flash('Databaseverbinding mislukt', 'error')
                return redirect(url_for('product_toevoegen'))

            try:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO producten (naam, beschrijving, prijs, categorie_id) VALUES (%s, %s, %s, %s) RETURNING id",
                    (naam, beschrijving, float(prijs), int(categorie_id))
                )
                product_id = cursor.fetchone()[0]

                for i in range(len(kleur_namen)):
                    kleur_foto_filename = save_image(kleur_fotos[i])
                    kleur_hover_foto_filename = save_image(kleur_hover_fotos[i])

                    if kleur_foto_filename and kleur_hover_foto_filename:
                        cursor.execute(
                            "INSERT INTO product_kleuren (product_id, kleur_naam, foto, hover_foto) VALUES (%s, %s, %s, %s)",
                            (product_id, kleur_namen[i], kleur_foto_filename, kleur_hover_foto_filename)
                        )
                    else:
                        raise Exception("Afbeeldingen voor een kleurvariant konden niet worden opgeslagen.")

                conn.commit()
                flash('Product succesvol toegevoegd!', 'success')
                return redirect(url_for('producten_per_categorie', categorie=get_categorie_naam(categorie_id)))

            except Exception as e:
                conn.rollback()
                print(f"Databasefout: {e}")
                flash(f'Databasefout: {str(e)}', 'error')
                return redirect(url_for('product_toevoegen'))
            finally:
                if conn:
                    conn.close()

        except Exception as e:
            print(f"Fout bij toevoegen product: {e}")
            flash(f'Fout bij toevoegen product: {str(e)}', 'error')
            return redirect(url_for('product_toevoegen'))

    return render_template('product_toevoegen.html', categorieen=categorieen)


@app.route('/producten/bewerken/<int:product_id>', methods=['GET', 'POST'])
def product_bewerken(product_id):
    if 'ingelogd' not in session or not session['ingelogd']:
        return redirect(url_for('beheren'))

    # GET Request - Toon bewerkformulier
    if request.method == 'GET':
        conn = get_db_connection()
        if not conn:
            flash('Databaseverbinding mislukt', 'error')
            return redirect(url_for('home'))

        try:
            cursor = conn.cursor(cursor_factory=DictCursor)

            # Haal product op met alle velden
            cursor.execute("SELECT * FROM producten WHERE id = %s", (product_id,))
            product = cursor.fetchone()

            if not product:
                flash('Product niet gevonden', 'error')
                return redirect(url_for('home'))

            # Haal alle kleuren op
            cursor.execute("SELECT * FROM product_kleuren WHERE product_id = %s ORDER BY id", (product_id,))
            kleuren = cursor.fetchall()

            # Haal alle categorieën op
            cursor.execute("SELECT * FROM categorieen")
            categorieen = cursor.fetchall()

            return render_template('product_bewerken.html',
                                   product=product,
                                   kleuren=kleuren,
                                   categorieen=categorieen,
                                   get_categorie_naam=get_categorie_naam) # <--- Dit is de belangrijke toevoeging!

        except Exception as e:
            print(f"FOUT bij ophalen product: {str(e)}")
            flash('Databasefout bij ophalen product', 'error')
            return redirect(url_for('home'))
        finally:
            if conn:
                conn.close()

    # POST Request - Verwerk formulier
    if request.method == 'POST':
        try:
            naam = request.form.get('naam')
            beschrijving = request.form.get('beschrijving')
            prijs = request.form.get('prijs')
            categorie_id = request.form.get('categorie_id')

            if not all([naam, beschrijving, prijs, categorie_id]):
                flash('Vul alle verplichte velden in', 'error')
                return redirect(url_for('product_bewerken', product_id=product_id))

            # Verwerk kleurvarianten
            kleur_namen = request.form.getlist('kleur_naam[]')
            kleur_fotos = request.files.getlist('kleur_foto[]')
            kleur_hover_fotos = request.files.getlist('kleur_hover_foto[]')

            conn = get_db_connection()
            if not conn:
                flash('Databaseverbinding mislukt', 'error')
                return redirect(url_for('product_bewerken', product_id=product_id))

            try:
                cursor = conn.cursor()

                # Update product basisinformatie
                cursor.execute(
                    "UPDATE producten SET naam = %s, beschrijving = %s, prijs = %s, categorie_id = %s WHERE id = %s",
                    (naam, beschrijving, float(prijs), int(categorie_id), product_id)
                )

                # Verwijder bestaande kleuren
                cursor.execute("DELETE FROM product_kleuren WHERE product_id = %s", (product_id,))

                # Voeg nieuwe kleurvarianten toe
                for i, kleur_naam in enumerate(kleur_namen):
                    if not kleur_naam.strip():
                        continue

                    # Verwerk afbeeldingen
                    oude_foto = request.form.get(f'oude_foto_{i}', '')
                    oude_hover_foto = request.form.get(f'oude_hover_foto_{i}', '')

                    # Behandel kleur foto
                    kleur_foto = oude_foto
                    if i < len(kleur_fotos) and kleur_fotos[i] and kleur_fotos[i].filename:
                        kleur_foto = save_image(kleur_fotos[i])
                        if not kleur_foto:
                            raise Exception(f"Kon kleurfoto {i + 1} niet opslaan")

                    # Behandel hover foto
                    kleur_hover_foto = oude_hover_foto
                    if i < len(kleur_hover_fotos) and kleur_hover_fotos[i] and kleur_hover_fotos[i].filename:
                        kleur_hover_foto = save_image(kleur_hover_fotos[i])
                        if not kleur_hover_foto:
                            raise Exception(f"Kon hoverfoto {i + 1} niet opslaan")

                    # Voeg kleurvariant toe
                    cursor.execute(
                        "INSERT INTO product_kleuren (product_id, kleur_naam, foto, hover_foto) VALUES (%s, %s, %s, %s)",
                        (product_id, kleur_naam, kleur_foto, kleur_hover_foto)
                    )

                conn.commit()
                flash('Product succesvol bijgewerkt!', 'success')
                return redirect(url_for('producten_per_categorie', categorie=get_categorie_naam(categorie_id)))

            except Exception as e:
                conn.rollback()
                print(f"FOUT tijdens bewerken product: {str(e)}")
                flash(f'Fout bij bijwerken product: {str(e)}', 'error')
                return redirect(url_for('product_bewerken', product_id=product_id))
            finally:
                if conn:
                    conn.close()

        except Exception as e:
            print(f"Fout bij bewerken product: {e}")
            flash('Er is een fout opgetreden bij het bewerken van het product', 'error')
            return redirect(url_for('product_bewerken', product_id=product_id))


@app.route('/producten/verwijderen/<int:product_id>', methods=['POST'])
def product_verwijderen(product_id):
    if 'ingelogd' not in session or not session['ingelogd']:
        return redirect(url_for('beheren'))

    conn = get_db_connection()
    if not conn:
        flash('Databaseverbinding mislukt', 'error')
        return redirect(url_for('home'))

    try:
        cursor = conn.cursor()

        # Eerst de kleurvarianten verwijderen (vanwege foreign key constraint)
        cursor.execute("DELETE FROM product_kleuren WHERE product_id = %s", (product_id,))

        # Dan het product zelf verwijderen
        cursor.execute("DELETE FROM producten WHERE id = %s", (product_id,))

        conn.commit()
        flash('Product succesvol verwijderd!', 'success')
    except Exception as e:
        conn.rollback()
        print(f"FOUT bij verwijderen product: {str(e)}")
        flash('Er is een fout opgetreden bij het verwijderen van het product', 'error')
    finally:
        if conn:
            conn.close()

    return redirect(url_for('home'))


# Overige routes (contact, login, profiel, etc.) blijven hetzelfde
@app.route('/contact')
def contact():
    return render_template('contact.html')


@app.route('/beheren', methods=['GET', 'POST'])
def beheren():
    if 'ingelogd' in session and session['ingelogd']:
        return render_template('home.html')

    if request.method == 'POST':
        gebruikersnaam = request.form.get('gebruikersnaam')
        wachtwoord = request.form.get('wachtwoord')

        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT id, wachtwoord_hash FROM gebruikers WHERE gebruikersnaam = %s",
                               (gebruikersnaam,))
                gebruiker = cursor.fetchone()

                if gebruiker and check_password_hash(gebruiker[1], wachtwoord):
                    session['ingelogd'] = True
                    session['gebruikersnaam'] = gebruikersnaam
                    session['gebruiker_id'] = gebruiker[0]
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


@app.route('/uitloggen')
def uitloggen():
    session.pop('ingelogd', None)
    session.pop('gebruikersnaam', None)
    session.pop('gebruiker_id', None)
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


if __name__ == '__main__':
    app.run(debug=True)