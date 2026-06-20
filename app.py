import os
from flask import Flask, request, jsonify
import pg8000
from google import genai
from google.genai import types
import json

app = Flask(__name__)


client = genai.Client(api_key=GEMINI_API_KEY)

def obtener_recetas_de_postgres():
    conn = pg8000.connect(
        user="root", password="root", host="localhost", port=5432, database="nido" 
    )
    cursor = conn.cursor()
    cursor.execute("SELECT nombre FROM recetas;") 
    filas = cursor.fetchall()
    cursor.close()
    conn.close()
    return [fila[0] for fila in filas]

@app.route('/api/ia/recomendar', methods=['POST'])
def recomendar_receta():
    data = request.get_json() or {}
    mensaje_usuario = data.get('mensaje', '')
    objetivo_nutricional = data.get('objetivo_nutricional', '')
    
    if not mensaje_usuario and not objetivo_nutricional:
        return jsonify({'error': 'Falta el campo "mensaje" o "objetivo_nutricional"'}), 400
        
    print(f"📩 Pedido desde .NET -> Mensaje: '{mensaje_usuario}' | Objetivo: '{objetivo_nutricional}'")
    
    try:
        recetas_en_bd = obtener_recetas_de_postgres()
        if not recetas_en_bd:
            return jsonify({'recetas': []}), 200

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
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt_usuario,
            config=types.GenerateContentConfig(system_instruction=instrucciones_sistema, temperature=0.1),
        )
        
        respuesta_raw = response.text.strip()
        try:
            lista_sugerida = json.loads(respuesta_raw)
        except Exception:
            cleaned = respuesta_raw.replace("```json", "").replace("```", "").strip()
            lista_sugerida = json.loads(cleaned)

        print(f"🤖 Gemini seleccionó: {lista_sugerida}")
        return jsonify({'recetas': lista_sugerida}), 200
        
    except Exception as e:
        print(f"❌ Error en IA: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)