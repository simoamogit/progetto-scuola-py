from flask import Flask, request, render_template, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from twilio.rest import Client
from apscheduler.schedulers.background import BackgroundScheduler
import os

app = Flask(__name__)

# Configura il database (qui uso SQLite per semplicità; in produzione puoi usare PostgreSQL)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///planner.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Modello per le verifiche/todo
class Verifica(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    materia = db.Column(db.String(100), nullable=False)
    data = db.Column(db.Date, nullable=False)
    ora = db.Column(db.Time, nullable=False)
    descrizione = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<Verifica {self.materia} {self.data} {self.ora}>'

# Configurazione di Twilio (imposta queste variabili d'ambiente sul tuo server cloud!)
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_WHATSAPP_NUMBER = os.environ.get('TWILIO_WHATSAPP_NUMBER')  # ad es. "whatsapp:+123456789"
MY_WHATSAPP_NUMBER = os.environ.get('MY_WHATSAPP_NUMBER')  # il tuo numero in formato "whatsapp:+123456789"

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Crea il database (se non esiste)
with app.app_context():
    db.create_all()

# Rotta principale: mostra una tabella con le verifiche
@app.route('/')
def index():
    verifiche = Verifica.query.order_by(Verifica.data, Verifica.ora).all()
    return render_template('index.html', verifiche=verifiche)

# Rotta per aggiungere una verifica tramite form web
@app.route('/aggiungiverifiche', methods=['GET', 'POST'])
def aggiungi():
    if request.method == 'POST':
        materia = request.form['materia']
        data_str = request.form['data']
        ora_str = request.form['ora']
        descrizione = request.form['descrizione']
        try:
            data_obj = datetime.strptime(data_str, '%Y-%m-%d').date()
            ora_obj = datetime.strptime(ora_str, '%H:%M').time()
        except ValueError:
            return "Formato data/ora non valido", 400
        nuova_verifica = Verifica(materia=materia, data=data_obj, ora=ora_obj, descrizione=descrizione)
        db.session.add(nuova_verifica)
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('\templates\aggiungi.html')

# API endpoint per aggiungere una verifica (JSON)
@app.route('/api/verifiche', methods=['POST'])
def api_aggiungi_verifica():
    data = request.get_json()
    materia = data.get('materia')
    data_str = data.get('data')
    ora_str = data.get('ora')
    descrizione = data.get('descrizione', '')
    if not (materia and data_str and ora_str):
        return jsonify({"error": "Dati mancanti"}), 400
    try:
        data_obj = datetime.strptime(data_str, '%Y-%m-%d').date()
        ora_obj = datetime.strptime(ora_str, '%H:%M').time()
    except ValueError:
        return jsonify({"error": "Formato data/ora non valido"}), 400
    nuova_verifica = Verifica(materia=materia, data=data_obj, ora=ora_obj, descrizione=descrizione)
    db.session.add(nuova_verifica)
    db.session.commit()
    return jsonify({"message": "Verifica aggiunta!", "id": nuova_verifica.id}), 201

# Rotta per gestire i messaggi in arrivo da Twilio (Webhook)
@app.route('/twilio', methods=['POST'])
def twilio_webhook():
    incoming_msg = request.values.get('Body', '').strip().lower()
    from_number = request.values.get('From', '')
    response_msg = "Ciao! Sono il Planner Scolastico Bot. Usa:\n" \
                   "'aggiungi <materia> <data YYYY-MM-DD> <ora HH:MM> <descrizione>' per aggiungere una verifica,\n" \
                   "oppure invia 'lista' per vedere le verifiche."
    
    if incoming_msg.startswith('aggiungi'):
        try:
            # Esempio: "aggiungi Matematica 2025-03-20 09:30 Prova sui polinomi"
            parts = incoming_msg.split(' ', 4)
            if len(parts) < 5:
                response_msg = "Formato non valido. Usa: aggiungi <materia> <data YYYY-MM-DD> <ora HH:MM> <descrizione>"
            else:
                _, materia, data_str, ora_str, descrizione = parts
                data_obj = datetime.strptime(data_str, '%Y-%m-%d').date()
                ora_obj = datetime.strptime(ora_str, '%H:%M').time()
                nuova_verifica = Verifica(materia=materia, data=data_obj, ora=ora_obj, descrizione=descrizione)
                db.session.add(nuova_verifica)
                db.session.commit()
                response_msg = f"Verifica per {materia} aggiunta per il {data_str} alle {ora_str}!"
        except Exception as e:
            response_msg = "Errore nell'aggiunta della verifica. Controlla il formato."
    elif incoming_msg.startswith('lista'):
        verifiche = Verifica.query.order_by(Verifica.data, Verifica.ora).all()
        if verifiche:
            response_msg = "Ecco le verifiche:\n"
            for v in verifiche:
                response_msg += f"{v.id}. {v.materia} - {v.data} {v.ora.strftime('%H:%M')} - {v.descrizione}\n"
        else:
            response_msg = "Nessuna verifica trovata."
    
    from twilio.twiml.messaging_response import MessagingResponse
    resp = MessagingResponse()
    resp.message(response_msg)
    return str(resp)

# Funzione per inviare notifiche automatiche (es. 1 giorno prima)
def invia_notifiche():
    soglia = datetime.now().date() + timedelta(days=1)
    verifiche = Verifica.query.filter(Verifica.data == soglia).all()
    if verifiche:
        for v in verifiche:
            msg = f"Promemoria: Hai una verifica di {v.materia} domani alle {v.ora.strftime('%H:%M')}!"
            try:
                twilio_client.messages.create(
                    body=msg,
                    from_=TWILIO_WHATSAPP_NUMBER,
                    to=MY_WHATSAPP_NUMBER  # In produzione, invia a tutti gli utenti registrati
                )
                print(f"Notifica inviata per {v.materia}")
            except Exception as e:
                print(f"Errore nell'invio della notifica per {v.materia}: {e}")

# Avvia un scheduler per controllare le notifiche ogni ora
scheduler = BackgroundScheduler()
scheduler.add_job(func=invia_notifiche, trigger="interval", hours=1)
scheduler.start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT") or 5000)
    app.run(host='0.0.0.0', port=port)
