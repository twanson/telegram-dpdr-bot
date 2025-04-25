# server.py
import os
import logging
import sys
import json
import stripe # <-- Añadir import
from datetime import datetime, timedelta, timezone # <-- Añadir datetime, timedelta, timezone
from flask import Flask, request, abort, jsonify
from dotenv import load_dotenv

# --- Importar desde bot.py ---
# Esto asume que bot.py está en el mismo directorio
# Puede ser frágil; refactorizar a un módulo compartido sería mejor a largo plazo
try:
    from bot import (
        update_user_plan,
        STRIPE_PRICE_ID_BASIC,
        STRIPE_PRICE_ID_PREMIUM,
        SUBSCRIPTION_PLANS # Necesario si quieres loguear el nombre del plan
    )
    logging.info("Funciones/constantes importadas correctamente desde bot.py")
except ImportError as e:
    logging.error(f"Error importando desde bot.py: {e}. El procesamiento de webhooks fallará.")
    # Definir stubs para evitar errores al iniciar si falla la importación
    def update_user_plan(user_id, plan, expiry): pass
    STRIPE_PRICE_ID_BASIC = None
    STRIPE_PRICE_ID_PREMIUM = None
    SUBSCRIPTION_PLANS = {}
# --- Fin Importar ---


# Cargar variables de entorno
load_dotenv()
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')
# Configurar la clave API de Stripe (necesaria para verificar webhooks si se usa la API)
# Stripe SDK usa STRIPE_SECRET_KEY automáticamente si está en env vars
if not os.getenv('STRIPE_SECRET_KEY'):
     logging.warning("STRIPE_SECRET_KEY no encontrada. La verificación de webhooks podría fallar si se usa la API.")


# Configurar logging básico para el servidor
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)

# --- Verificación inicial del Webhook Secret ---
if not STRIPE_WEBHOOK_SECRET:
    logging.critical("¡ERROR CRÍTICO! STRIPE_WEBHOOK_SECRET no está configurado en las variables de entorno. "
                     "El webhook no funcionará de forma segura.")
    # Podrías decidir salir si es absolutamente esencial, aunque Flask seguirá corriendo.
    # sys.exit(1)
# --- Fin Verificación ---

# Crear la aplicación Flask
app = Flask(__name__)

@app.route('/')
def index():
    return "Webhook server is running."

@app.route('/webhook/stripe', methods=['POST'])
def stripe_webhook():
    logging.info("[Webhook] Inicio del procesamiento.")
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    event = None

    if not STRIPE_WEBHOOK_SECRET:
         logging.error("[Webhook] Falta STRIPE_WEBHOOK_SECRET, abortando.")
         abort(500) # Error interno del servidor
         return '', 500

    logging.info("[Webhook] Intentando verificar firma...")
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
        logging.info(f"[Webhook] Firma verificada OK. Event ID: {event.get('id')}, Type: {event.get('type')}")

    except ValueError as e:
        logging.error(f"[Webhook] Error ValueError en construct_event (payload/secreto inválido): {e}")
        abort(400)
        return '', 400
    except stripe.error.SignatureVerificationError as e:
        logging.error(f"[Webhook] Error SignatureVerificationError en construct_event (firma inválida): {e}")
        abort(400)
        return '', 400
    except Exception as e:
        logging.error(f"[Webhook] Error genérico en construct_event: {e}")
        abort(500)
        return '', 500

    logging.info(f"[Webhook] Verificando tipo de evento: {event.get('type')}")
    if event.get('type') == 'checkout.session.completed':
        logging.info("[Webhook] Evento es checkout.session.completed. Procesando...")
        session = event['data']['object']
        logging.info(f"[Webhook] ID de sesión: {session.get('id')}")

        client_reference_id = session.get('client_reference_id')
        subscription_id = session.get('subscription')
        payment_status = session.get('payment_status')
        logging.info(f"[Webhook] Datos extraídos: client_ref='{client_reference_id}', sub_id='{subscription_id}', payment_status='{payment_status}'")

        if payment_status == 'paid' and client_reference_id and subscription_id:
            logging.info("[Webhook] Condición payment_status=='paid' y IDs presentes CUMPLIDA.")
            try:
                logging.info("[Webhook] Entrando en el bloque try para procesar datos...")
                user_id = int(client_reference_id)
                logging.info(f"[Webhook] User ID parseado: {user_id}")

                logging.info(f"[Webhook] Intentando obtener detalles de suscripción: {subscription_id}")
                try:
                    subscription = stripe.Subscription.retrieve(subscription_id)
                    price_id = subscription['items']['data'][0]['price']['id']
                    logging.info(f"[Webhook] Subscription recuperada OK. Price ID: {price_id}")
                except Exception as e:
                    logging.error(f"[Webhook] Error obteniendo detalles de suscripción {subscription_id} para user {user_id}: {e}")
                    price_id = None

                target_plan = None
                expiry_date_iso = None

                logging.info(f"[Webhook] Determinando plan para Price ID: {price_id}")
                if price_id == STRIPE_PRICE_ID_BASIC:
                    target_plan = 'BASIC'
                elif price_id == STRIPE_PRICE_ID_PREMIUM:
                    target_plan = 'PREMIUM'
                else:
                    logging.warning(f"[Webhook] Price ID desconocido ({price_id}) para user {user_id}. No se actualizará plan.")

                logging.info(f"[Webhook] Plan determinado: {target_plan}. Procediendo a actualizar BD si aplica.")
                if target_plan:
                    expiry_date = datetime.now(timezone.utc) + timedelta(days=30)
                    expiry_date_iso = expiry_date.date().isoformat()
                    logging.info(f"[Webhook] Datos para BD: user={user_id}, plan={target_plan}, expira={expiry_date_iso}")

                    try:
                        logging.info("[Webhook] Llamando a update_user_plan...")
                        if callable(update_user_plan):
                           success = update_user_plan(user_id, target_plan, expiry_date_iso)
                           if success:
                               logging.info(f"[Webhook] ✅ update_user_plan retornó éxito para user {user_id}.")
                           else:
                               logging.error(f"[Webhook] ❌ update_user_plan retornó fallo para user {user_id}.")
                        else:
                           logging.error("[Webhook] ❌ update_user_plan no es callable.")
                    except Exception as e:
                        logging.error(f"[Webhook] ❌ Excepción al llamar a update_user_plan: {e}")
                else:
                    logging.info("[Webhook] No se determinó un target_plan válido, no se llama a update_user_plan.")

            except (ValueError, TypeError) as e:
                logging.error(f"[Webhook] Error parseando client_reference_id '{client_reference_id}': {e}")
            except Exception as e:
                 logging.error(f"[Webhook] Error inesperado procesando sesión {session.get('id')} para user {client_reference_id}: {e}")

        else:
            logging.warning(f"[Webhook] Condición payment_status=='paid' y IDs presentes NO CUMPLIDA. No se procesa pago.")

    else:
        logging.info(f"[Webhook] Evento de tipo {event.get('type')} no manejado.")

    logging.info("[Webhook] Enviando respuesta 200 OK a Stripe.")
    return jsonify({'status': 'received'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080)) # Cambiado default a 8080 por si acaso
    logging.info(f"Iniciando servidor Flask en el puerto {port}")
    app.run(host='0.0.0.0', port=port) 