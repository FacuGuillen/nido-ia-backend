import os
from flask import Flask, request, jsonify
import pg8000
from google import genai
from google.genai import types
import json

app = Flask(__name__)

# =====================================================================
# 🔑 CONFIGURACIÓN DE GEMINI
# =====================================================================
# Pegá acá tu clave de Google AI Studio temporalmente para testear rápido:
GEMINI_API_KEY = ""

# Inicializamos el cliente oficial de Google
client = genai.Client(api_key=GEMINI_API_KEY)


# =====================================================================
# 1. TU FUNCIÓN REAL QUE CONECTA A POSTGRES EN DOCKER
# =====================================================================
def obtener_recetas_de_postgres():
    conn = pg8000.connect(
        user="root",
        password="root", 
        host="localhost", # Como Flask corre nativo en Windows, usa localhost para hablar con Docker
        port=5432,
        database="nido"
    )
    cursor = conn.cursor()
    cursor.execute("SELECT nombre FROM recetas;") # Le saqué el LIMIT por si tenés más platos cargados
    filas = cursor.fetchall()
    cursor.close()
    conn.close()
    return [fila[0] for fila in filas]


# =====================================================================
# 2. ENDPOINT DINÁMICO CON IA REAL PARA .NET
# =====================================================================
# @app.route('/api/ia/recomendar', methods=['POST'])
# def recomendar_receta():
#     data = request.get_json() or {}
#     mensaje_usuario = data.get('mensaje', '')
    
#     if not mensaje_usuario:
#         return jsonify({'error': 'Falta el campo "mensaje" en el JSON'}), 400
        
#     print(f"📩 Pedido desde .NET: '{mensaje_usuario}'")
    
#     try:
#         # 1. Buscamos de forma REAL los nombres de platos en tu base de datos de Postgres
#         recetas_en_bd = obtener_recetas_de_postgres()
        
#         if not recetas_en_bd:
#             print("⚠️ La base de datos de recetas está vacía.")
#             return jsonify({'receta': 'NONE'}), 200

#         # 2. Formateamos la lista de platos para que Gemini los pueda leer bien
#         lista_recetas_txt = "\n".join([f"- {r}" for r in recetas_en_bd])
        
#         # 3. Le definimos el rol estricto al modelo (System Instruction)
#         instrucciones_sistema = (
#             "Sos el motor de recomendación semántica de la app de cocina Nido.\n"
#             "Tu objetivo es leer el antojo o descripción del usuario y elegir cuál de las recetas disponibles "
#             "en la base de datos se adapta mejor por contexto, tipo de plato o ingredientes.\n\n"
#             "REGLAS CRUCIALES Y ESTRICTAS:\n"
#             "1. Responde ÚNICAMENTE con el nombre exacto de la receta elegida, idéntico a cómo figura en la lista.\n"
#             "2. No agregues introducciones, ni comentarios, ni explicaciones, ni punto final. Solo el string del nombre.\n"
#             "3. Si la frase del usuario no tiene ningún sentido culinario o no se relaciona con ningún plato de la lista, responde: NONE."
#         )
        
#         # 4. Diseñamos el prompt inyectando los datos de tu Postgres en vivo
#         prompt_usuario = (
#             f"Lista de recetas reales en la base de datos:\n{lista_recetas_txt}\n\n"
#             f"Pedido/Antojo del usuario: '{mensaje_usuario}'\n\n"
#             f"Receta recomendada:"
#         )
        
#         # 5. Llamamos al cerebro de Google (Gemini 2.5 Flash)
#         response = client.models.generate_content(
#             model='gemini-2.5-flash',
#             contents=prompt_usuario,
#             config=types.GenerateContentConfig(
#                 system_instruction=instrucciones_sistema,
#                 temperature=0.1, # Súper baja para que sea preciso y no invente nombres raros
#             ),
#         )
        
#         # Limpiamos cualquier espacio o salto de línea fantasma del output de Google
#         receta_sugerida = response.text.strip()
        
#         print(f"🤖 Gemini analizó el contexto y seleccionó: '{receta_sugerida}'")
#         return jsonify({'receta': receta_sugerida}), 200
        
#     except Exception as e:
#         print(f"❌ Error interno en la IA: {str(e)}")
#         return jsonify({'error': 'Error interno del servidor de Python'}), 500

@app.route('/api/ia/recomendar', methods=['POST'])
def recomendar_receta():
    data = request.get_json() or {}
    mensaje_usuario = data.get('mensaje', '')
    
    if not mensaje_usuario:
        return jsonify({'error': 'Falta el campo "mensaje" en el JSON'}), 400
        
    print(f"📩 Pedido desde .NET: '{mensaje_usuario}'")
    
    try:
        recetas_en_bd = obtener_recetas_de_postgres()
        
        if not recetas_en_bd:
            return jsonify({'recetas': []}), 200

        lista_recetas_txt = "\n".join([f"- {r}" for r in recetas_en_bd])
        
        # 🌟 NUEVO SYSTEM INSTRUCTION: Le pedimos un JSON estructurado
        instrucciones_sistema = (
            "Sos el motor de recomendación semántica de la app de cocina Nido.\n"
            "Tu objetivo es leer el antojo, ingredientes o contexto del usuario y seleccionar "
            "TODAS las recetas de la lista que cumplan o se relacionen con la búsqueda.\n\n"
            "REGLAS ESTRICTAS DE RESPUESTA:\n"
            "1. Debes responder ÚNICAMENTE con un formato JSON que sea un array de strings.\n"
            "   Ejemplo: [\"Arroz con zucchini\", \"Arroz pakistaní\"]\n"
            "2. Usa los nombres EXACTOS de la lista provista, sin alterar mayúsculas ni acentos.\n"
            "3. Si el usuario pide un ingrediente general (ej: 'arroz'), incluye todas las recetas que lo contengan.\n"
            "4. Si ninguna receta coincide en absoluto, responde con un array vacío: []\n"
            "5. No agregues texto por fuera del bloque JSON (ni saludos, ni marcas de código como ```json)."
        )
        
        prompt_usuario = (
            f"Lista de recetas reales en la base de datos:\n{lista_recetas_txt}\n\n"
            f"Pedido/Antojo del usuario: '{mensaje_usuario}'\n\n"
            f"Recetas seleccionadas en formato JSON array:"
        )
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt_usuario,
            config=types.GenerateContentConfig(
                system_instruction=instrucciones_sistema,
                temperature=0.1,
            ),
        )
        
        # Limpiamos la respuesta por las dudas
        respuesta_raw = response.text.strip()
        
        # 🌟 Intentamos parsear lo que escupió Gemini como una lista real de Python
        try:
            lista_sugerida = json.loads(respuesta_raw)
            if not isinstance(lista_sugerida, list):
                lista_sugerida = [respuesta_raw] # Por si acaso devolvió un string suelto
        except Exception:
            # Si Gemini metió la pata con el formato, limpiamos caracteres raros
            cleaned = respuesta_raw.replace("```json", "").replace("```", "").strip()
            lista_sugerida = json.loads(cleaned)

        print(f"🤖 Gemini analizó el contexto y seleccionó {len(lista_sugerida)} receta(s): {lista_sugerida}")
        
        # Devolvemos el array a .NET
        return jsonify({'recetas': lista_sugerida}), 200
        
    except Exception as e:
        print(f"❌ Error interno en la IA: {str(e)}")
        return jsonify({'error': 'Error interno del servidor de Python'}), 500

if __name__ == '__main__':
    print("🚀 Microservicio de IA DINÁMICO escuchando en http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)