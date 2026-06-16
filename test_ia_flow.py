import sys
import pg8000.dbapi
from google import genai
from google.genai import types

# =====================================================================
# 1. TRAER EL MENÚ COMPLETO DESDE POSTGRES (DOCKER)
# =====================================================================
def obtener_todas_las_recetas():
    connection = None
    try:
        connection = pg8000.dbapi.connect(
            host="127.0.0.1", port=5432, database="nido", user="root", password="root"
        )
        cursor = connection.cursor()
        # Traemos las 10 recetas reales sin límites raros
        cursor.execute("SELECT nombre FROM recetas;")
        resultados = cursor.fetchall()
        return [fila[0] for fila in resultados]
    except Exception as error:
        print(f"❌ Error al obtener recetas: {error}")
        return []
    finally:
        if connection:
            cursor.close()
            connection.close()

# =====================================================================
# 2. CONSULTAR UNA RECETA ESPECÍFICA Y SUS INGREDIENTES
# =====================================================================
def buscar_receta_e_ingredientes(nombre_receta):
    connection = None
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        print("🔌 Conectando a la base de datos con pg8000...")
        print(f"🔍 Buscando en la base de datos: '{nombre_receta}'...\n")

        connection = pg8000.dbapi.connect(
            host="127.0.0.1", port=5432, database="nido", user="root", password="root"
        )
        cursor = connection.cursor()

        query = """
            SELECT r.nombre, r.porciones, ir.nombre_ingrediente, ir.cantidad, ir.unidad
            FROM recetas r
            INNER JOIN ingredientes_receta ir ON r.id = ir.receta_id
            WHERE r.nombre ILIKE %s;
        """
        cursor.execute(query, (f"%{nombre_receta}%",))
        resultados = cursor.fetchall()

        if not resultados:
            print(f"❌ No se encontró la receta '{nombre_receta}' en la base de datos.")
            return

        print(f"🍲 ¡Receta Encontrada!: {resultados[0][0]}")
        print(f"👥 Porciones: {resultados[0][1]}")
        print("-" * 50)
        print("🛒 Ingredientes necesarios:")
        for fila in resultados:
            cantidad = fila[3] if fila[3] is not None else ""
            unidad = fila[4] if fila[4] is not None else ""
            print(f"   • {fila[2]}: {cantidad} {unidad}")
    except Exception as error:
        print(f"❌ Error real en la base de datos: {error}")
    finally:
        if connection:
            cursor.close()
            connection.close()

# =====================================================================
# 3. LA INTELIGENCIA ARTIFICIAL REAL (GEMINI 2.5 FLASH)
# =====================================================================
def procesar_pedido_con_ia(texto_usuario, recetas_disponibles):
    client = genai.Client(api_key="")
    menu_para_ia = "\n".join([f"- {r}" for r in recetas_disponibles])
    
    system_instruction = f"""
    Sos un asistente de cocina inteligente para la app 'Nido'. 
    Tu único trabajo es recibir el mensaje del usuario y entender cuál de las siguientes recetas de nuestra base de datos quiere preparar.
    
    Recetas disponibles actualmente en el sistema:
    {menu_para_ia}
    
    Debes responder ÚNICAMENTE con el nombre exacto de la receta (respetando mayúsculas y espacios). 
    Si el usuario pide algo que no está en la lista o no se entiende, respondé con la palabra: NONE
    """
    
    print(f"🤖 IA pensando qué querés comer...")
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=texto_usuario,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.1 
        )
    )
    return response.text.strip()

# =====================================================================
# 4. CONSOLA INTERACTIVA REAL
# =====================================================================
if __name__ == "__main__":
    recetas_en_bd = obtener_todas_las_recetas()
    print("=" * 60)
    print(f"📚 Base de datos sincronizada. {len(recetas_en_bd)} platos listos para la IA.")
    print("💡 Escribí 'salir' para cerrar.\n")
    print("=" * 60)

    while True:
        pedido = input("💬 ¿Qué tenés ganas de comer hoy? --> ")
        
        if pedido.lower().strip() == "salir":
            print("\n👋 ¡Chau Facu! Éxitos.")
            break
            
        if not pedido.strip():
            continue

        print() 
        receta_api = procesar_pedido_con_ia(pedido, recetas_en_bd)
        print(f"🎯 Gemini interpretó que querés: '{receta_api}'\n")
        
        if receta_api != "NONE":
            buscar_receta_e_ingredientes(receta_api)
        else:
            print("❌ La IA no pudo asociar tu pedido a ninguna receta del sistema.")
            
        print("\n" + "="*50 + "\n")