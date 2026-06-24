import os
from flask import Flask, request, jsonify
import pg8000
from google import genai
from google.genai import types
import json

app = Flask(__name__)


client = genai.Client(api_key=GEMINI_API_KEY)

def obtener_recetas_de_postgres():
    conn = None
    cursor = None
    try:
        conn = pg8000.connect(
            user="root", password="root", host="localhost", port=5432, database="nido" 
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
    
    if not mensaje_usuario and not objetivo_nutricional:
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
        if cantidad_palabras == 1:
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

        instrucciones_sistema = (
            "Sos el motor de recomendación de la app Nido. Tu único objetivo es seleccionar "
            "los nombres de las recetas que cumplan con el criterio del usuario.\n\n"
            "REGLAS:\n"
            "1. Responde ÚNICAMENTE con un JSON array de objetos: [{\"nombre\": \"Nombre Exacto\"}]\n"
            "2. Usa los nombres EXACTOS de la lista.\n"
            "3. Si no hay coincidencias, responde: []\n"
            f"{filtro_nutricional_txt}"
        )
        
        prompt_usuario = f"Lista de recetas:\n{lista_recetas_txt}\n\nPedido: '{mensaje_usuario}'\n\nJSON:"
        
        print("📡 Enviando payload a Google GenAI...")
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt_usuario,
            config=types.GenerateContentConfig(
                system_instruction=instrucciones_sistema, 
                temperature=0.1,
                response_mime_type="application/json"
            ),
        )
        
        respuesta_raw = response.text.strip()
        print(f"📥 Respuesta cruda de IA: {respuesta_raw}")
        
        lista_sugerida = json.loads(respuesta_raw)
        print(f"🤖 [MODO IA] Éxito. Enviando: {lista_sugerida}")
        return jsonify({'recetas': lista_sugerida}), 200
        
    except Exception as e:
        print(f"❌ Error en la ejecución: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)