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
        host="localhost", 
        port=5432,
        database="nido" 
    )
    
    cursor = conn.cursor()
    cursor.execute("SELECT nombre FROM recetas;") 
    filas = cursor.fetchall()
    cursor.close()
    conn.close()
    return [fila[0] for fila in filas]


# =====================================================================
# 2. ENDPOINT DINÁMICO CON IA REAL PARA .NET
# =====================================================================

@app.route('/api/ia/recomendar', methods=['POST'])
def recomendar_receta():
    data = request.get_json() or {}
    mensaje_usuario = data.get('mensaje', '')
    objetivo_nutricional = data.get('objetivo_nutricional', '') # <-- Capturamos el filtro
    
    # Validamos que al menos venga uno de los dos criterios
    if not mensaje_usuario and not objetivo_nutricional:
        return jsonify({'error': 'Falta el campo "mensaje" o "objetivo_nutricional" en el JSON'}), 400
        
    print(f"📩 Pedido desde .NET -> Mensaje: '{mensaje_usuario}' | Objetivo: '{objetivo_nutricional}'")
    
    try:
        recetas_en_bd = obtener_recetas_de_postgres()
        
        if not recetas_en_bd:
            return jsonify({'recetas': []}), 200

        lista_recetas_txt = "\n".join([f"- {r}" for r in recetas_en_bd])
        
        # 🎯 Armamos la regla extra para Gemini según el select de Angular
        filtro_nutricional_txt = ""
        if objetivo_nutricional == "alta-proteina":
            filtro_nutricional_txt = "6. REGLA NUTRICIONAL CRÍTICA: Filtrá y seleccioná ÚNICAMENTE recetas que sean altas en proteínas (que tengan carnes, huevos, legumbres o lácteos).\n"
        elif objetivo_nutricional == "bajo-calorias":
            filtro_nutricional_txt = "6. REGLA NUTRICIONAL CRÍTICA: Filtrá y seleccioná ÚNICAMENTE recetas que sean ligeras o bajas en calorías (predominio de vegetales, ensaladas, preparaciones livianas).\n"
        elif objetivo_nutricional == "vegetariano":
            filtro_nutricional_txt = "6. REGLA NUTRICIONAL CRÍTICA: Excluí por completo cualquier receta que contenga carne de cualquier tipo (vaca, pollo, pescado, cerdo, etc.). Solo permití platos basados en vegetales, legumbres, huevos o queso.\n"

        # 🌟 INSTRUCCIONES DEL SISTEMA ACTUALIZADAS
        instrucciones_sistema = (
            "Sos el motor de recomendación semántica de la app de cocina Nido.\n"
            "Tu objetivo es leer el antojo, ingredientes o contexto del usuario, aplicar las reglas nutricionales "
            "si existen, y seleccionar TODAS las recetas de la lista que cumplan o se relacionen con la búsqueda.\n\n"
            "REGLAS ESTRICTAS DE RESPUESTA:\n"
            "1. Debes responder ÚNICAMENTE con un formato JSON que sea un array de strings.\n"
            "   Ejemplo: [\"Arroz con zucchini\", \"Arroz pakistaní\"]\n"
            "2. Usa los nombres EXACTOS de la lista provista, sin alterar mayúsculas ni acentos.\n"
            "3. Si el usuario pide un ingrediente general (ej: 'arroz'), incluye todas las recetas que lo contengan.\n"
            "4. Si ninguna receta coincide en absoluto con los criterios o con las restricciones nutricionales, responde con un array vacío: []\n"
            "5. No agregues texto por fuera del bloque JSON (ni saludos, ni marcas de código como ```json).\n"
            f"{filtro_nutricional_txt}" # <-- Le metemos la regla en la cabeza a Gemini
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
        
        respuesta_raw = response.text.strip()
        
        try:
            lista_sugerida = json.loads(respuesta_raw)
            if not isinstance(lista_sugerida, list):
                lista_sugerida = [respuesta_raw]
        except Exception:
            cleaned = respuesta_raw.replace("```json", "").replace("```", "").strip()
            lista_sugerida = json.loads(cleaned)

        print(f"🤖 Gemini analizó el contexto y seleccionó {len(lista_sugerida)} receta(s): {lista_sugerida}")
        
        return jsonify({'recetas': lista_sugerida}), 200
        
    except Exception as e:
        print(f"❌ Error interno en la IA: {str(e)}")
        return jsonify({'error': 'Error interno del servidor de Python'}), 500
    
    # =====================================================================
# 🚀 ARRANQUE DEL SERVIDOR NATIVO
# =====================================================================
if __name__ == '__main__':
    # Lo levantamos en el puerto 5000 y con debug=True para que se reinicie solo si editás el código
    app.run(host='0.0.0.0', port=5000, debug=True)