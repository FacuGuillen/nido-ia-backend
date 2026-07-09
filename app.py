import os
import json
from flask import Flask, request, jsonify
import pg8000
from google import genai
from google.genai import types
from google.genai.errors import ClientError


try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(path=".env"):
        if not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as env_file:
            for line in env_file:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()

app = Flask(__name__)


def get_genai_client():
    api_key = os.environ.get("GOOGLE_GENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Falta configurar GOOGLE_GENAI_API_KEY")
    return genai.Client(api_key=api_key)


def get_model_name():
    return (os.environ.get("GOOGLE_GENAI_MODEL", "gemini-2.0-flash") or "gemini-2.0-flash").strip()


def generar_respuesta_fallback(pregunta, receta_nombre="", alacena=None, historial=None):
    pregunta_lower = (pregunta or "").strip().lower()
    alacena = alacena or []
    alacena_texto = ", ".join(alacena) if alacena else "ingredientes básicos"

    if "vegetar" in pregunta_lower or "vegano" in pregunta_lower:
        propuesta = "un bowl de quinoa con garbanzos, verduras asadas y un toque de yogur vegetal"
    elif "prote" in pregunta_lower or "muscular" in pregunta_lower:
        propuesta = "un plato de pollo o tofu salteado con arroz y verduras"
    elif "rápido" in pregunta_lower or "facil" in pregunta_lower or "rápida" in pregunta_lower:
        propuesta = "una tortilla de papa y cebolla con una ensalada simple"
    elif "ligero" in pregunta_lower or "bajo calor" in pregunta_lower or "salud" in pregunta_lower:
        propuesta = "una ensalada tibia con pollo, legumbres y quinoa"
    else:
        propuesta = "una pasta con tomate, espinaca y queso o un arroz con verduras y huevo"

    if receta_nombre:
        return (
            f"Podés probar {propuesta} como alternativa compatible con {receta_nombre}. "
            f"Si querés, te doy una versión más económica, rápida o usando {alacena_texto}."
        )

    return (
        f"Podés preparar {propuesta}. "
        f"Si querés, te ayudo a adaptarlo con los ingredientes que tenés en casa: {alacena_texto}."
    )


def obtener_recetas_fallback(mensaje_usuario, objetivo_nutricional, restricciones, recetas_en_bd):
    texto = (mensaje_usuario or "").strip().lower()
    objetivo = (objetivo_nutricional or "").strip().lower()
    restricciones_normalizadas = {str(r).strip().lower() for r in restricciones or []}

    palabras = [p for p in texto.replace("/", " ").split() if len(p) > 2]
    if not palabras and not objetivo and not restricciones_normalizadas:
        return []

    resultados = []
    for receta in recetas_en_bd:
        nombre_lower = receta.lower()
        score = 0

        if texto and texto in nombre_lower:
            score += 8

        for palabra in palabras:
            if palabra in nombre_lower:
                score += 3

        if objetivo == "vegetariano" and any(token in nombre_lower for token in ["vegetariano", "veggie", "ensalada", "tortilla", "arroz", "pasta", "sopa", "curry"]):
            score += 1

        if "sin tacc" in restricciones_normalizadas or "sin gluten" in restricciones_normalizadas:
            if any(token in nombre_lower for token in ["sin tacc", "gluten", "harina", "pan"]):
                score -= 4

        if "vegetariano" in restricciones_normalizadas:
            if any(token in nombre_lower for token in ["carne", "pollo", "pescado", "salmon", "vacuna", "cerdo", "jamon", "chorizo"]):
                score -= 6

        if score > 0:
            resultados.append((score, receta))

    resultados.sort(key=lambda item: item[0], reverse=True)
    return [{"nombre": nombre} for _, nombre in resultados[:8]]


def llamar_gemini(prompt_usuario, instrucciones_sistema, temperature=0.1, response_mime_type=None):
    client = get_genai_client()
    model_name = get_model_name()
    config_kwargs = {
        "system_instruction": instrucciones_sistema,
        "temperature": temperature,
    }
    if response_mime_type:
        config_kwargs["response_mime_type"] = response_mime_type

    try:
        return client.models.generate_content(
            model=model_name,
            contents=prompt_usuario,
            config=types.GenerateContentConfig(**config_kwargs),
        )
    except ClientError as exc:
        status_code = getattr(exc, "status_code", None)
        detail = str(exc)
        if status_code == 404 or "NOT_FOUND" in detail.upper():
            raise RuntimeError(
                f"El modelo '{model_name}' no está disponible. Cambiá GOOGLE_GENAI_MODEL en el .env o usá un modelo soportado."
            ) from exc
        if status_code == 429 or "RESOURCE_EXHAUSTED" in detail.upper():
            raise RuntimeError(
                "La IA no pudo responder porque se agotó la cuota o límite de requests de Gemini. Revisá el plan/billing o esperá unos minutos."
            ) from exc
        raise RuntimeError(f"Error al llamar a Gemini: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"Error al llamar a Gemini: {str(exc)}") from exc
def obtener_recetas_de_postgres():
    conn = None
    cursor = None
    try:
        conn = pg8000.connect(
            user=os.environ.get("NIDO_DB_USER", "root"),
            password=os.environ.get("NIDO_DB_PASSWORD", "root"),
            host=os.environ.get("NIDO_DB_HOST", "localhost"),
            port=int(os.environ.get("NIDO_DB_PORT", "5432")),
            database=os.environ.get("NIDO_DB_NAME", "nido"),
        )
        cursor = conn.cursor()
        cursor.execute("SELECT nombre FROM recetas;") 
        filas = cursor.fetchall()
        return [fila[0] for fila in filas]
    except Exception as db_err:
        print(f"❌ Error crítico en Base de Datos: {str(db_err)}")
        return []
    finally:
        # Nos aseguramos de liberar los recursos de Postgres SIEMPRE
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route('/api/ia/recomendar', methods=['POST', 'GET'])
def recomendar_receta():
    if request.method == 'POST':
        data = request.get_json() or {}
    else:
        data = request.args or {}
        
    mensaje_usuario = data.get('mensaje', data.get('busqueda', '')).strip()
    objetivo_nutricional = data.get('objetivo_nutricional', data.get('objetivo', ''))
    restricciones = data.get('restricciones', [])
    if isinstance(restricciones, str):
        restricciones = [item.strip() for item in restricciones.split(',') if item.strip()]
    elif not isinstance(restricciones, list):
        restricciones = []
    
    if not mensaje_usuario and not objetivo_nutricional and not restricciones:
        return jsonify({'error': 'Falta el campo "mensaje" o "objetivo_nutricional"'}), 400
        
    print(f"\n📩 NUEVA PETICIÓN -> Mensaje: '{mensaje_usuario}' | Objetivo: '{objetivo_nutricional}'")
    
    try:
        print("⏳ Trayendo recetas de Postgres...")
        recetas_en_bd = obtener_recetas_de_postgres()
        if not recetas_en_bd:
            print("⚠️ Base de datos vacía o caída.")
            return jsonify({'recetas': []}), 200

        palabras_usuario = mensaje_usuario.strip().split()
        cantidad_palabras = len(palabras_usuario) if mensaje_usuario else 0
        print(f"📊 Cantidad de palabras detectadas: {cantidad_palabras}")

        # --- MODO BUSCADOR SIMPLE (1 Sola Palabra) ---
        if cantidad_palabras == 1 and not restricciones:
            palabra_clave = palabras_usuario[0].lower()
            print(f"🔍 [MODO TRADICIONAL] Buscando palabra clave: '{palabra_clave}'")
            
            lista_sugerida = []
            for receta in recetas_en_bd:
                if palabra_clave in receta.lower():
                    lista_sugerida.append({"nombre": receta})
            
            print(f"🔍 [MODO TRADICIONAL] Éxito. Enviando: {lista_sugerida}")
            return jsonify({'recetas': lista_sugerida}), 200

        # --- MODO IA (2 Palabras o más) ---
        print(f"🤖 [MODO IA] Conectando con Gemini 2.5...")
        lista_recetas_txt = "\n".join([f"- {r}" for r in recetas_en_bd])
        
        filtro_nutricional_txt = ""
        if objetivo_nutricional == "alta-proteina":
            filtro_nutricional_txt = "6. REGLA NUTRICIONAL CRÍTICA: Filtrá ÚNICAMENTE recetas altas en proteínas.\n"
        elif objetivo_nutricional == "bajo-calorias":
            filtro_nutricional_txt = "6. REGLA NUTRICIONAL CRÍTICA: Filtrá ÚNICAMENTE recetas bajas en calorías.\n"
        elif objetivo_nutricional == "vegetariano":
            filtro_nutricional_txt = "6. REGLA NUTRICIONAL CRÍTICA: Excluí recetas con carne.\n"

        reglas_restricciones = []
        restricciones_normalizadas = {str(restriccion).strip().lower() for restriccion in restricciones}
        if "sin tacc" in restricciones_normalizadas or "sin gluten" in restricciones_normalizadas:
            reglas_restricciones.append("Excluí recetas con gluten, harina de trigo, pan común, pasta común, masa común o avena no certificada.")
        if "vegetariano" in restricciones_normalizadas:
            reglas_restricciones.append("Excluí recetas con carne, pollo, pescado o mariscos.")
        if "vegano" in restricciones_normalizadas:
            reglas_restricciones.append("Excluí recetas con carne, pollo, pescado, mariscos, lácteos, huevo o miel.")
        if "sin lactosa" in restricciones_normalizadas:
            reglas_restricciones.append("Excluí recetas con leche, queso, crema, manteca, yogur, ricota o dulce de leche.")

        filtro_restricciones_txt = ""
        if reglas_restricciones:
            filtro_restricciones_txt = "7. RESTRICCIONES DEL HOGAR: " + " ".join(reglas_restricciones) + "\n"

        instrucciones_sistema = (
            "Sos el motor de recomendación de la app Nido. Tu único objetivo es seleccionar "
            "los nombres de las recetas que cumplan con el criterio del usuario.\n\n"
            "REGLAS:\n"
            "1. Responde ÚNICAMENTE con un JSON array de objetos: [{\"nombre\": \"Nombre Exacto\"}]\n"
            "2. Usa los nombres EXACTOS de la lista.\n"
            "3. Si no hay coincidencias, responde: []\n"
            f"{filtro_nutricional_txt}"
            f"{filtro_restricciones_txt}"
        )
        
        prompt_usuario = f"Lista de recetas:\n{lista_recetas_txt}\n\nPedido: '{mensaje_usuario}'\n\nJSON:"
        
        print("📡 Enviando payload a Google GenAI...")
        try:
            response = llamar_gemini(
                prompt_usuario,
                instrucciones_sistema,
                temperature=0.1,
                response_mime_type="application/json",
            )

            respuesta_raw = response.text.strip()
            print(f"📥 Respuesta cruda de IA: {respuesta_raw}")

            lista_sugerida = json.loads(respuesta_raw)
            print(f"🤖 [MODO IA] Éxito. Enviando: {lista_sugerida}")
            return jsonify({'recetas': lista_sugerida}), 200
        except Exception as exc:
            print(f"⚠️ Gemini falló, usando fallback por palabras clave: {exc}")
            lista_sugerida = obtener_recetas_fallback(
                mensaje_usuario,
                objetivo_nutricional,
                restricciones,
                recetas_en_bd,
            )
            print(f"🔎 Fallback: {lista_sugerida}")
            return jsonify({'recetas': lista_sugerida, 'fallback': True}), 200
        
    except Exception as e:
        print(f"❌ Error en la ejecución: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/ia/asistente', methods=['POST'])
def asistente_recetas():
    data = request.get_json() or {}
    pregunta = (data.get('pregunta') or '').strip()
    receta = data.get('receta')
    alacena = data.get('alacena') or []
    historial = data.get('historial') or []

    if not pregunta:
        return jsonify({'error': 'Falta el campo "pregunta"'}), 400

    receta_nombre = ''
    ingredientes = []
    faltantes = []
    if isinstance(receta, dict):
        receta_nombre = receta.get('nombre') or ''
        ingredientes = receta.get('ingredientes') or []
        faltantes = receta.get('faltantes') or []

    historial_txt = []
    for mensaje in historial[-8:]:
        if not isinstance(mensaje, dict):
            continue
        role = mensaje.get('role', 'user')
        text = mensaje.get('text', '')
        if text:
            historial_txt.append(f"{role}: {text}")

    contexto_receta = "No hay receta seleccionada."
    if receta_nombre:
        contexto_receta = (
            f"Receta seleccionada: {receta_nombre}\n"
            f"Ingredientes de la receta: {', '.join(ingredientes) if ingredientes else 'sin datos'}\n"
            f"Ingredientes faltantes detectados: {', '.join(faltantes) if faltantes else 'sin faltantes detectados'}"
        )

    contexto_alacena = ', '.join(alacena) if alacena else 'sin datos de alacena'
    contexto_historial = "\n".join(historial_txt) if historial_txt else "Sin historial previo."

    instrucciones_sistema = """
Sos el asistente culinario de Nido.
Responde en español rioplatense, simple, breve y practico.
Si hay una receta seleccionada, prioriza reemplazos compatibles con esa receta y con la alacena del usuario.
Si no hay receta seleccionada, responde como asistente general de cocina.
Si sugeris algo que podria buscarse como receta en Nido, deci que luego puede buscarlo en el buscador, sin intentar filtrar ni navegar.
No inventes disponibilidad exacta: si no aparece en la alacena, presentalo como sugerencia general.
Inclui una advertencia corta si el reemplazo puede cambiar textura, coccion o alergenos.
No respondas con JSON; responde solo el texto para el usuario.
""".strip()

    prompt_usuario = f"""
Contexto de receta:
{contexto_receta}

Alacena disponible:
{contexto_alacena}

Historial reciente:
{contexto_historial}

Pregunta actual:
{pregunta}
""".strip()

    try:
        response = llamar_gemini(
            prompt_usuario,
            instrucciones_sistema,
            temperature=0.4,
        )

        respuesta = (response.text or '').strip()
        if not respuesta:
            return jsonify({'respuesta': generar_respuesta_fallback(pregunta, receta_nombre, alacena, historial)}), 200

        return jsonify({'respuesta': respuesta}), 200
    except Exception as e:
        print(f"❌ Error en asistente de recetas: {str(e)}")
        return jsonify({'respuesta': generar_respuesta_fallback(pregunta, receta_nombre, alacena, historial)}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
