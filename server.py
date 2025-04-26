# server.py
import os
import logging
import sys
import json
import stripe
import httpx # <-- Añadir import
from datetime import datetime, timedelta, timezone # <-- Añadir datetime, timedelta, timezone
from flask import Flask, request, abort, jsonify
from dotenv import load_dotenv

# --- Importar desde bot.py ---
# Esto asume que bot.py está en el mismo directorio
# Puede ser frágil; refactorizar a un módulo compartido sería mejor a largo plazo
try:
    from bot import (
        update_user_plan,
        update_user_stripe_customer_id,
        get_user_by_customer_id,
        STRIPE_PRICE_ID_BASIC,
        STRIPE_PRICE_ID_PREMIUM,
        SUBSCRIPTION_PLANS # Necesario si quieres loguear el nombre del plan
    )
    logging.info("Funciones/constantes importadas correctamente desde bot.py")
except ImportError as e:
    logging.error(f"Error importando desde bot.py: {e}. El procesamiento de webhooks fallará.")
    # Definir stubs para evitar errores al iniciar si falla la importación
    def update_user_plan(user_id, plan, expiry): pass
    def update_user_stripe_customer_id(user_id, customer_id): pass
    def get_user_by_customer_id(customer_id): return None
    STRIPE_PRICE_ID_BASIC = None
    STRIPE_PRICE_ID_PREMIUM = None
    SUBSCRIPTION_PLANS = {}
# --- Fin Importar ---


# Cargar variables de entorno
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN') # <-- Necesitamos el token aquí
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

# --- Verificación inicial del Webhook Secret y BOT_TOKEN ---
if not STRIPE_WEBHOOK_SECRET:
    logging.critical("¡ERROR CRÍTICO! STRIPE_WEBHOOK_SECRET no está configurado en las variables de entorno. "
                     "El webhook no funcionará de forma segura.")
    # Podrías decidir salir si es absolutamente esencial, aunque Flask seguirá corriendo.
    # sys.exit(1)
if not BOT_TOKEN:
    logging.critical("¡ERROR CRÍTICO! BOT_TOKEN no está configurado...")
# --- Fin Verificación ---

# Crear la aplicación Flask
app = Flask(__name__)

@app.route('/')
def index():
    return "Webhook server is running."

# --- Función auxiliar asíncrona para enviar mensaje ---
async def send_telegram_message(user_id: int, text: str):
    if not BOT_TOKEN:
        logging.error("[TelegramSend] No BOT_TOKEN available.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': user_id,
        'text': text,
        'parse_mode': 'Markdown' # Opcional: para formato
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10)
            response.raise_for_status() # Lanza excepción si hay error HTTP (4xx o 5xx)
            logging.info(f"[TelegramSend] Mensaje de confirmación enviado a user {user_id}. Respuesta: {response.status_code}")
    except httpx.RequestError as exc:
        logging.error(f"[TelegramSend] Error de red/conexión enviando mensaje a user {user_id}: {exc}")
    except httpx.HTTPStatusError as exc:
        logging.error(f"[TelegramSend] Error HTTP enviando mensaje a user {user_id}: {exc.response.status_code} - {exc.response.text}")
    except Exception as e:
        logging.error(f"[TelegramSend] Error inesperado enviando mensaje a user {user_id}: {e}", exc_info=True)
# --- Fin Función auxiliar --- 

@app.route('/webhook/stripe', methods=['POST'])
async def stripe_webhook(): # <<< Hacer la función async >>>
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
        logging.error(f"[Webhook] Error GENÉRICO INESPERADO en construct_event: {e}", exc_info=True)
        event = None

    if event is None:
        logging.error("[Webhook] Evento es None después del bloque de verificación. No se procesará más.")
        return jsonify({'status': 'verification_failed_or_error'}), 200

    logging.info(f"[Webhook] Verificando tipo de evento: {event.get('type')}")
    if event.get('type') == 'checkout.session.completed':
        logging.info("[Webhook] Evento es checkout.session.completed. Procesando...")
        session = event['data']['object']
        logging.info(f"[Webhook] ID de sesión: {session.get('id')}")

        client_reference_id = session.get('client_reference_id')
        subscription_id = session.get('subscription')
        payment_status = session.get('payment_status')
        stripe_customer_id = session.get('customer')
        logging.info(f"[Webhook] Datos extraídos: client_ref='{client_reference_id}', sub_id='{subscription_id}', payment_status='{payment_status}', customer_id='{stripe_customer_id}'")

        if payment_status == 'paid' and client_reference_id and subscription_id and stripe_customer_id:
            logging.info("[Webhook] Condición payment_status=='paid' y IDs presentes CUMPLIDA.")
            try:
                logging.info("[Webhook] Entrando en el bloque try para procesar datos...")
                user_id = int(client_reference_id)
                logging.info(f"[Webhook] User ID parseado: {user_id}")

                # Guardar el Customer ID de Stripe en la BD
                try:
                    if callable(update_user_stripe_customer_id):
                        update_user_stripe_customer_id(user_id, stripe_customer_id)
                    else:
                         logging.error("[Webhook] ❌ update_user_stripe_customer_id no es callable.")
                except Exception as e_cust:
                    logging.error(f"[Webhook] ❌ Excepción al llamar a update_user_stripe_customer_id: {e_cust}")
                # --- Fin guardar customer ID ---

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
                               # <<< ENVIAR MENSAJE DE CONFIRMACIÓN >>>
                               plan_name = SUBSCRIPTION_PLANS.get(target_plan, {}).get('name', target_plan)
                               expiry_date_formatted = datetime.fromisoformat(expiry_date_iso).strftime('%d/%m/%Y')
                               confirmation_text = (
                                   f"¡Felicidades! 🎉 Tu suscripción al **{plan_name}** está activa.\n"
                                   f"Ahora disfrutas de sus beneficios hasta el **{expiry_date_formatted}**.\n\n"
                                   f"Puedes usar /plan para ver los detalles."
                               )
                               await send_telegram_message(user_id, confirmation_text)
                               # <<< FIN ENVIAR MENSAJE >>>
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

    elif event.get('type') == 'customer.subscription.deleted':
        logging.info("[Webhook] Evento es customer.subscription.deleted. Procesando cancelación...")
        subscription = event['data']['object']
        customer_id = subscription.get('customer')
        subscription_id = subscription.get('id')
        canceled_at_timestamp = subscription.get('canceled_at')
        
        # Formatear fecha de cancelación si existe
        canceled_at_str = "N/A"
        if canceled_at_timestamp:
            try:
                canceled_at_dt = datetime.fromtimestamp(canceled_at_timestamp, timezone.utc)
                canceled_at_str = canceled_at_dt.strftime('%Y-%m-%d %H:%M:%S %Z')
            except Exception as date_e:
                logging.error(f"[Webhook] Error formateando fecha canceled_at: {date_e}")
        
        logging.info(f"[Webhook] Cancelación recibida para customer {customer_id}, sub {subscription_id}, cancelada en {canceled_at_str}")

        if customer_id and callable(get_user_by_customer_id) and callable(update_user_plan):
            logging.info(f"[Webhook] Buscando usuario por Customer ID: {customer_id}")
            user_info = get_user_by_customer_id(customer_id)
            
            if user_info:
                user_id = user_info['user_id']
                logging.info(f"[Webhook] Usuario {user_id} encontrado. Actualizando plan a FREE.")
                try:
                    success = update_user_plan(user_id, 'FREE', None) # Volver a FREE, sin expiración
                    if success:
                        logging.info(f"[Webhook] ✅ Plan actualizado a FREE para user {user_id} debido a cancelación.")
                        # <<< ENVIAR MENSAJE DE CANCELACIÓN (Opcional) >>>
                        cancellation_text = (
                            f"Tu suscripción ha sido cancelada correctamente. "
                            f"Has vuelto al plan Gratuito."
                            # f"Puedes volver a suscribirte usando /upgrade en cualquier momento."
                        )
                        # Necesitaríamos saber el idioma del usuario... podríamos añadirlo a la BD o 
                        # simplemente enviar en un idioma por defecto o no enviar.
                        # await send_telegram_message(user_id, cancellation_text) 
                        # <<< FIN MENSAJE >>>
                    else:
                        logging.error(f"[Webhook] ❌ update_user_plan (a FREE) falló para user {user_id}.")
                except Exception as e_plan:
                    logging.error(f"[Webhook] ❌ Excepción al llamar a update_user_plan (a FREE): {e_plan}")
            else:
                logging.warning(f"[Webhook] No se encontró usuario en la BD para customer {customer_id} que canceló suscripción {subscription_id}. No se puede actualizar plan.")
        else:
             logging.error("[Webhook] No se pudo procesar cancelación: falta customer_id o funciones auxiliares.")

    else:
        logging.info(f"[Webhook] Evento de tipo {event.get('type')} no manejado.")

    logging.info("[Webhook] Enviando respuesta 200 OK a Stripe.")
    return jsonify({'status': 'received'}), 200

# --- Rutas de Redirección de Stripe --- 
@app.route('/stripe-success')
def stripe_success():
    # Podrías pasar el session_id como parámetro si quisieras personalizar el mensaje,
    # pero por ahora un mensaje genérico es suficiente.
    # session_id = request.args.get('session_id')
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Pago Exitoso</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: sans-serif; text-align: center; padding: 40px; background-color: #f0fdf4; color: #14532d; }
            h1 { color: #16a34a; }
        </style>
    </head>
    <body>
        <h1>¡Pago Completado con Éxito!</h1>
        <p>Tu suscripción ha sido activada.</p>
        <p>Ya puedes cerrar esta ventana y volver a tu chat de Telegram.</p>
        <p>🎉</p>
    </body>
    </html>
    """

@app.route('/stripe-cancel')
def stripe_cancel():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Pago Cancelado</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: sans-serif; text-align: center; padding: 40px; background-color: #fffbeb; color: #713f12; }
            h1 { color: #facc15; }
        </style>
    </head>
    <body>
        <h1>Pago Cancelado</h1>
        <p>Has cancelado el proceso de pago.</p>
        <p>Puedes cerrar esta ventana y volver a Telegram. Si cambias de opinión, puedes usar /upgrade de nuevo.</p>
        <p>😕</p>
    </body>
    </html>
    """
# --- Fin Rutas de Redirección ---

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    logging.info(f"Iniciando servidor Flask en el puerto {port}")
    app.run(host='0.0.0.0', port=port) 