# server.py
import os
import logging
import sys
import json
from flask import Flask, request, abort, jsonify # <-- Añadir jsonify
from dotenv import load_dotenv

# Cargar variables de entorno (necesitaremos el webhook secret más tarde)
load_dotenv()
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')

# Configurar logging básico para el servidor
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)

# Crear la aplicación Flask
app = Flask(__name__)

@app.route('/')
def index():
    # Una ruta simple para verificar que el servidor está vivo
    return "Webhook server is running."

@app.route('/webhook/stripe', methods=['POST'])
def stripe_webhook():
    """Escucha las notificaciones POST de Stripe."""
    logging.info("Webhook de Stripe recibido...")

    payload = request.data
    event = None

    # Por ahora, solo logueamos el payload crudo.
    # Más tarde añadiremos la verificación de firma y el procesamiento del evento.
    try:
        # Asegurarse que payload no está vacío
        if not payload:
             logging.warning("Webhook recibido con payload vacío.")
             abort(400)
             return '', 400
             
        logging.info(f"Payload recibido: {payload.decode('utf-8')}")
        # Aquí iría la lógica de verificación de firma y parseo del evento
        # event = stripe.Webhook.construct_event(
        #     payload, sig_header, STRIPE_WEBHOOK_SECRET
        # )
    except ValueError as e:
        # Payload inválido
        logging.error(f"Webhook Error: Payload inválido - {e}")
        abort(400)
        return '', 400
    except Exception as e:
        logging.error(f"Webhook Error: Otro error - {e}")
        abort(500) # Error interno del servidor
        return '', 500


    # Procesar el evento (FASE 3)
    # if event['type'] == 'checkout.session.completed':
    #     session = event['data']['object']
    #     logging.info(f"CheckoutSession completado: {session['id']}")
    #     # Extraer user_id y actualizar BD...
    # else:
    #     logging.info(f"Evento no manejado: {event['type']}")
    #     pass

    # Enviar respuesta a Stripe confirmando recepción
    return jsonify({'status': 'success'}), 200

if __name__ == '__main__':
    # Railway proporciona el puerto a través de la variable PORT
    port = int(os.environ.get('PORT', 5000))
    # Escuchar en 0.0.0.0 para aceptar conexiones externas en Railway
    logging.info(f"Iniciando servidor Flask en el puerto {port}")
    app.run(host='0.0.0.0', port=port) 