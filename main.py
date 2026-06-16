from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI()

# 1. Definimos la estructura de los datos que van a llegar desde .NET
class ItemStock(BaseModel):
    nombre: str
    cantidad: float
    unidad: str

class IngredienteReceta(BaseModel):
    nombre: str
    cantidad_base_por_persona: float
    unidad: str

class RecetaEstructurada(BaseModel):
    id: int
    nombre: str
    instrucciones: str
    usuario_id: Optional[int] = None  # NULL si es del catálogo general, Int si es propia
    ingredientes: List[IngredienteReceta]

class ConsultaNido(BaseModel):
    cantidad_personas: int    
    stock_actual: List[ItemStock]
    recetas_disponibles: List[RecetaEstructurada] # .NET le manda tanto las globales como las del usuario


# 2. Diccionario inteligente para emparejar ingredientes (Español / Inglés / Sinónimos)
TABLA_SINONIMOS = {
    "ajo": ["garlic", "diente de ajo", "ajos"],
    "tomate triturado": ["chopped tomatoes", "tomato", "salsa de tomate", "puré de tomate", "tomate"],
    "fideos": ["penne rigate", "pasta", "spaghetti", "tallarines"],
    "aceite de oliva": ["olive oil", "aceite"],
    "garbanzos": ["chickpeas", "garbanzo"],
    "harina de trigo": ["harina", "flour", "harina 0000", "harina 000"]
}

def buscar_en_stock(nombre_ingrediente_receta: str, stock_usuario: list):
    """Busca un ingrediente en el stock del usuario usando la tabla de sinónimos."""
    ing_clean = nombre_ingrediente_receta.lower().strip()
    
    # Buscamos si el ingrediente de la receta matchéa con algún sinónimo conocido
    for nombre_estandar, sinonimos in TABLA_SINONIMOS.items():
        if ing_clean == nombre_estandar or ing_clean in sinonimos:
            for item in stock_usuario:
                if item.nombre.lower().strip() == nombre_estandar:
                    return item.cantidad
                    
    # Si no está en la tabla de sinónimos, buscamos coincidencia de texto directa
    for item in stock_usuario:
        if item.nombre.lower().strip() == ing_clean:
            return item.cantidad
            
    return 0.0


# 3. El Endpoint que va a consumir .NET desde el Backend
@app.post("/ia/analizar-recetas")
def analizar_menu_disponible(consulta: ConsultaNido):
    personas = consulta.cantidad_personas
    recetas_sugeridas = []
    
    # La IA recorre cada receta enviada por .NET (sin importar de quién sea)
    for receta in consulta.recetas_disponibles:
        faltantes = {}
        cantidades_totales_receta = {}
        
        for ing in receta.ingredientes:
            # Calculamos cuánto se necesita en total para la cantidad de personas actual
            total_necesario = ing.cantidad_base_por_persona * personas
            cantidades_totales_receta[ing.nombre] = f"{total_necesario} {ing.unidad}"
            
            # Nos fijamos cuánto tiene el usuario en la heladera (SQL Server -> .NET -> Python)
            cantidad_en_stock = buscar_en_stock(ing.nombre, consulta.stock_actual)
            
            # Si no le alcanza, lo sumamos a la lista de faltantes
            if cantidad_en_stock < total_necesario:
                faltantes[ing.nombre] = f"{total_necesario - cantidad_en_stock} {ing.unidad}"
        
        # Guardamos el análisis de esta receta
        recetas_sugeridas.append({
            "receta_id": receta.id,
            "nombre": receta.nombre,
            "es_propia_del_usuario": receta.usuario_id is not None,
            "te_alcanza": len(faltantes) == 0,
            "cantidades_totales_necesarias": cantidades_totales_receta,
            "lo_que_te_falta_comprar": faltantes
        })
        
    return {
        "mensaje_ia": f"Análisis completado para {personas} personas.",
        "resultado_analisis": recetas_sugeridas
    }