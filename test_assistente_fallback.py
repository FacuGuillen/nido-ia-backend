import unittest

from app import generar_respuesta_fallback


class AsistenteFallbackTests(unittest.TestCase):
    def test_tarta_de_pollo_sugiere_reemplazo(self):
        respuesta = generar_respuesta_fallback(
            "quiero hacer una tarta de pollo pero no tengo pollo, que puedo hacer ?"
        )
        self.assertIn("tarta", respuesta.lower())
        self.assertIn("garbanzos", respuesta.lower())
        self.assertIn("queso", respuesta.lower())

    def test_desayuno_proteico_sugiere_huevo_yogur(self):
        respuesta = generar_respuesta_fallback("quiero un desayuno proteico")
        self.assertIn("huevo", respuesta.lower())
        self.assertIn("yogur", respuesta.lower())

    def test_milanesas_sugiere_reemplazo(self):
        respuesta = generar_respuesta_fallback("A Javi le gustan las milanesas")
        self.assertIn("milanesa", respuesta.lower())
        self.assertIn("soja", respuesta.lower())

    def test_contexto_conversacional_reconoce_seguimiento(self):
        historial = [
            {"role": "user", "text": "quiero hacer empanadas vegetarianas"},
            {"role": "assistant", "text": "Sí, se pueden hacer con soja texturizada."},
        ]
        respuesta = generar_respuesta_fallback("y si no tengo cebolla?", historial=historial)
        self.assertIn("cebolla", respuesta.lower())
        self.assertIn("reempl", respuesta.lower())

    def test_pregunta_no_entendida_pide_aclaracion(self):
        respuesta = generar_respuesta_fallback("caca")
        self.assertIn("no entend", respuesta.lower())
        self.assertIn("ayudar", respuesta.lower())

    def test_ejemplo_de_reemplazo_responde_con_sugerencia_general(self):
        respuesta = generar_respuesta_fallback("por ejemplo cual me recomendas ?")
        self.assertIn("reemplazo", respuesta.lower())
        self.assertIn("arom", respuesta.lower())

    def test_tarta_de_pescado_debe_responder_con_idea_concreta(self):
        respuesta = generar_respuesta_fallback("quiero hacer una tarta de pescado, que me recomendas ?")
        self.assertIn("tarta", respuesta.lower())
        self.assertIn("pescado", respuesta.lower())
        self.assertIn("verd", respuesta.lower())

    def test_falta_cebolla_en_salsa_debe_ofrecer_reemplazo_practico(self):
        respuesta = generar_respuesta_fallback("no tengo cebolla para la salsa")
        self.assertIn("cebolla", respuesta.lower())
        self.assertIn("ajo", respuesta.lower())


if __name__ == "__main__":
    unittest.main()
