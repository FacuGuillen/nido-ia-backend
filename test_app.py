import unittest
from os import environ
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app as app_module


class DependencyManifestTests(unittest.TestCase):
    def test_uses_pinned_openai_and_gunicorn_without_gemini(self):
        requirements = Path("requirements.txt").read_text(encoding="utf-8").splitlines()

        self.assertIn("openai==2.11.0", requirements)
        self.assertIn("gunicorn==23.0.0", requirements)
        self.assertFalse(any(line.startswith("google-genai==") for line in requirements))
        self.assertFalse(any(line.startswith("google-auth==") for line in requirements))


class OpenAIClientTests(unittest.TestCase):
    @patch.dict(environ, {"OPENAI_API_KEY": "  test-key  ", "OPENAI_MODEL": "test-model"})
    @patch("app.OpenAI")
    def test_creates_client_from_trimmed_environment_api_key(self, openai_class):
        client = app_module.get_openai_client()

        openai_class.assert_called_once_with(api_key="test-key")
        self.assertIs(client, openai_class.return_value)

    @patch.dict(environ, {"OPENAI_API_KEY": "   ", "OPENAI_MODEL": "test-model"})
    def test_rejects_blank_api_key(self):
        with self.assertRaisesRegex(RuntimeError, "^OpenAI API key not configured$"):
            app_module.get_openai_client()

    @patch.dict(environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "   "})
    def test_rejects_blank_model(self):
        with self.assertRaisesRegex(RuntimeError, "^OpenAI model not configured$"):
            app_module.get_openai_client()


class RecommendationConfigurationTests(unittest.TestCase):
    @patch.dict(environ, {"OPENAI_API_KEY": ""})
    @patch("app.obtener_recetas_de_postgres", return_value=["Pollo al horno"])
    def test_missing_openai_api_key_returns_safe_contract_error(self, _recipes):
        response = app_module.app.test_client().post(
            "/api/ia/recomendar",
            json={"mensaje": "algo ligero"},
        )

        self.assertEqual(500, response.status_code)
        self.assertEqual(
            {"error": "OpenAI API key not configured"},
            response.get_json(),
        )


class RecommendationNormalizationTests(unittest.TestCase):
    def test_normalizes_json_wrapper_to_exact_database_names(self):
        result = app_module.normalize_recommendations(
            '{"recetas": [{"nombre": "Pollo al horno"}]}',
            ["Pollo al horno", "Tarta de verduras"],
        )

        self.assertEqual([{"nombre": "Pollo al horno"}], result)

    def test_normalizes_legacy_string_array(self):
        result = app_module.normalize_recommendations(
            '["Tarta de verduras"]',
            ["Pollo al horno", "Tarta de verduras"],
        )

        self.assertEqual([{"nombre": "Tarta de verduras"}], result)

    def test_rejects_malformed_json(self):
        with self.assertRaisesRegex(ValueError, "^Invalid recommendation response$"):
            app_module.normalize_recommendations("not-json", ["Pollo al horno"])

    def test_rejects_unknown_recipe_name(self):
        with self.assertRaisesRegex(ValueError, "^Invalid recommendation response$"):
            app_module.normalize_recommendations(
                '{"recetas": [{"nombre": "Inventada"}]}',
                ["Pollo al horno"],
            )


class OpenAICompletionTests(unittest.TestCase):
    @patch.dict(environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test-model"})
    @patch("app.get_openai_client")
    def test_complete_uses_runtime_model_and_json_object_mode(self, get_client):
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"recetas": []}'))]
        )
        get_client.return_value.chat.completions.create.return_value = completion
        messages = [{"role": "user", "content": "Recommend dinner"}]

        result = app_module.complete(messages, temperature=0.1, json_mode=True)

        self.assertEqual('{"recetas": []}', result)
        get_client.return_value.chat.completions.create.assert_called_once_with(
            model="test-model",
            messages=messages,
            temperature=0.1,
            response_format={"type": "json_object"},
        )

    @patch.dict(environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": ""})
    def test_complete_rejects_blank_runtime_model(self):
        with self.assertRaisesRegex(RuntimeError, "^OpenAI model not configured$"):
            app_module.complete([], temperature=0.1)


class OpenAIRecommendationRouteTests(unittest.TestCase):
    @patch("app.complete")
    @patch(
        "app.obtener_recetas_de_postgres",
        return_value=["Pollo al horno", "Tarta de verduras"],
    )
    def test_single_word_search_uses_local_exact_database_names(
        self,
        _recipes,
        complete,
    ):
        response = app_module.app.test_client().post(
            "/api/ia/recomendar",
            json={"mensaje": "pollo"},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {"recetas": [{"nombre": "Pollo al horno"}]},
            response.get_json(),
        )
        complete.assert_not_called()

    @patch("app.complete")
    @patch("app.obtener_recetas_de_postgres", return_value=[])
    def test_empty_database_returns_empty_contract_without_provider(
        self,
        _recipes,
        complete,
    ):
        response = app_module.app.test_client().post(
            "/api/ia/recomendar",
            json={"mensaje": "algo ligero para cenar"},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual({"recetas": []}, response.get_json())
        complete.assert_not_called()

    @patch.dict(environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test-model"})
    @patch("app.complete", return_value='{"recetas": [{"nombre": "Tarta de verduras"}]}')
    @patch(
        "app.obtener_recetas_de_postgres",
        return_value=["Pollo al horno", "Tarta de verduras"],
    )
    def test_multi_word_request_uses_openai_and_preserves_contract(
        self,
        _recipes,
        complete,
    ):
        response = app_module.app.test_client().post(
            "/api/ia/recomendar",
            json={
                "mensaje": "algo ligero para cenar",
                "restricciones": ["vegetariano"],
            },
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {"recetas": [{"nombre": "Tarta de verduras"}]},
            response.get_json(),
        )
        self.assertTrue(complete.call_args.kwargs["json_mode"])


class RecommendationErrorTests(unittest.TestCase):
    @patch.dict(environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test-model"})
    @patch("app.complete", side_effect=Exception("secret-provider-detail"))
    @patch("app.obtener_recetas_de_postgres", return_value=["Pollo al horno"])
    def test_provider_failure_returns_safe_service_error(
        self,
        _recipes,
        _complete,
    ):
        response = app_module.app.test_client().post(
            "/api/ia/recomendar",
            json={"mensaje": "algo con pollo"},
        )

        self.assertEqual(500, response.status_code)
        self.assertEqual(
            {"error": "Recommendation service unavailable"},
            response.get_json(),
        )
        self.assertNotIn("secret-provider-detail", response.get_data(as_text=True))

    @patch.dict(environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test-model"})
    @patch("app.complete", return_value="not-json")
    @patch("app.obtener_recetas_de_postgres", return_value=["Pollo al horno"])
    def test_unparseable_response_returns_safe_validation_error(
        self,
        _recipes,
        _complete,
    ):
        response = app_module.app.test_client().post(
            "/api/ia/recomendar",
            json={"mensaje": "algo con pollo"},
        )

        self.assertEqual(500, response.status_code)
        self.assertEqual(
            {"error": "Invalid recommendation response"},
            response.get_json(),
        )


class AssistantRouteTests(unittest.TestCase):
    @patch.dict(environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test-model"})
    @patch("app.complete", return_value="Podés reemplazarlo por garbanzos.")
    def test_assistant_preserves_response_shape(self, complete):
        response = app_module.app.test_client().post(
            "/api/ia/asistente",
            json={
                "pregunta": "¿Con qué reemplazo el pollo?",
                "receta": {"nombre": "Tarta", "ingredientes": ["pollo"]},
                "alacena": ["garbanzos"],
            },
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {"respuesta": "Podés reemplazarlo por garbanzos."},
            response.get_json(),
        )
        self.assertFalse(complete.call_args.kwargs["json_mode"])

    @patch.dict(environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test-model"})
    @patch("app.complete", side_effect=Exception("secret-provider-detail"))
    def test_assistant_provider_failure_returns_safe_error(self, _complete):
        response = app_module.app.test_client().post(
            "/api/ia/asistente",
            json={"pregunta": "¿Qué puedo cocinar?"},
        )

        self.assertEqual(500, response.status_code)
        self.assertEqual(
            {"error": "Assistant service unavailable"},
            response.get_json(),
        )
        self.assertNotIn("secret-provider-detail", response.get_data(as_text=True))

    @patch.dict(environ, {"OPENAI_API_KEY": "", "OPENAI_MODEL": "test-model"})
    def test_assistant_missing_api_key_returns_configuration_error(self):
        response = app_module.app.test_client().post(
            "/api/ia/asistente",
            json={"pregunta": "¿Qué puedo cocinar?"},
        )

        self.assertEqual(500, response.status_code)
        self.assertEqual(
            {"error": "OpenAI API key not configured"},
            response.get_json(),
        )

    def test_assistant_requires_question(self):
        response = app_module.app.test_client().post(
            "/api/ia/asistente",
            json={},
        )

        self.assertEqual(400, response.status_code)
        self.assertEqual({"error": 'Falta el campo "pregunta"'}, response.get_json())


class HealthEndpointTests(unittest.TestCase):
    @patch.dict(environ, {"OPENAI_API_KEY": "", "OPENAI_MODEL": ""})
    @patch("app.get_openai_client")
    def test_live_health_is_provider_independent(self, get_client):
        client = app_module.app.test_client()

        live_response = client.get("/health/live")
        compatibility_response = client.get("/health")

        self.assertEqual(200, live_response.status_code)
        self.assertEqual({"status": "ok"}, live_response.get_json())
        self.assertEqual(200, compatibility_response.status_code)
        self.assertEqual({"status": "ok"}, compatibility_response.get_json())
        get_client.assert_not_called()

    @patch.dict(environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test-model"})
    @patch("app.get_openai_client")
    @patch("app.database_is_ready", return_value=True, create=True)
    def test_ready_health_checks_config_and_database_without_provider(
        self,
        database_is_ready,
        get_client,
    ):
        response = app_module.app.test_client().get("/health/ready")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ready"}, response.get_json())
        database_is_ready.assert_called_once_with()
        get_client.assert_not_called()

    @patch.dict(environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test-model"})
    @patch("app.database_is_ready", return_value=False, create=True)
    def test_ready_health_reports_unavailable_database(self, database_is_ready):
        response = app_module.app.test_client().get("/health/ready")

        self.assertEqual(503, response.status_code)
        self.assertEqual({"status": "not ready"}, response.get_json())
        database_is_ready.assert_called_once_with()

    @patch.dict(environ, {"OPENAI_API_KEY": "", "OPENAI_MODEL": ""})
    @patch("app.database_is_ready", create=True)
    def test_ready_health_reports_missing_runtime_config(self, database_is_ready):
        response = app_module.app.test_client().get("/health/ready")

        self.assertEqual(503, response.status_code)
        self.assertEqual({"status": "not ready"}, response.get_json())
        database_is_ready.assert_not_called()


class DeliveryArtifactTests(unittest.TestCase):
    def test_dockerfile_runs_gunicorn_and_probes_live_health(self):
        dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

        self.assertIn("FROM python:3.14-slim", dockerfile)
        self.assertIn("gunicorn", dockerfile)
        self.assertIn("app:app", dockerfile)
        self.assertIn("${APP_PORT}", dockerfile)
        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn("/health/live", dockerfile)
        self.assertNotIn("--debug", dockerfile)

    def test_dockerignore_excludes_secrets_tests_and_local_metadata(self):
        ignored = Path(".dockerignore").read_text(encoding="utf-8").splitlines()

        for required_entry in (
            ".git",
            ".env",
            ".venv/",
            "venv/",
            "__pycache__/",
            "test*.py",
            "openspec/",
        ):
            self.assertIn(required_entry, ignored)

    def test_publish_workflow_uses_full_sha_and_refuses_existing_tag(self):
        workflow = Path(".github/workflows/publish-image.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("dev-ia", workflow)
        self.assertIn("python -m unittest discover", workflow)
        self.assertIn("DOCKERHUB_IMAGE", workflow)
        self.assertIn("sha-${GITHUB_SHA}", workflow)
        self.assertIn("docker manifest inspect", workflow)
        self.assertIn("already exists", workflow)
        self.assertIn("/health/live", workflow)

    def test_publish_workflow_pushes_stable_channel_tag(self):
        workflow = Path(".github/workflows/publish-image.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("recetas-ia-nido-v1", workflow)
        self.assertIn('docker tag "${IMAGE}:${TAG}" "${IMAGE}:recetas-ia-nido-v1"', workflow)
        self.assertIn('docker push "${IMAGE}:recetas-ia-nido-v1"', workflow)
        self.assertIn('docker push "${IMAGE}:${TAG}"', workflow)

    def test_env_example_documents_runtime_variables_without_secrets(self):
        env_example = Path(".env.example").read_text(encoding="utf-8")

        required_variables = (
            "OPENAI_API_KEY",
            "OPENAI_MODEL",
            "NIDO_DB_HOST",
            "NIDO_DB_PORT",
            "NIDO_DB_NAME",
            "NIDO_DB_USER",
            "NIDO_DB_PASSWORD",
            "APP_PORT",
        )
        for variable in required_variables:
            self.assertIn(variable, env_example)

        self.assertNotIn("sk-", env_example)
        self.assertNotIn("gpt-4", env_example)


class RuntimeCleanupTests(unittest.TestCase):
    def test_no_gemini_runtime_or_manual_script_remains(self):
        sources = [Path("app.py")]
        legacy_script = Path("test_ia_flow.py")
        if legacy_script.exists():
            sources.append(legacy_script)

        combined = "\n".join(path.read_text(encoding="utf-8") for path in sources)
        self.assertNotIn("google.genai", combined.lower())
        self.assertNotIn("from google import genai", combined.lower())
        self.assertNotIn("gemini", combined.lower())
        self.assertNotIn("GOOGLE_GENAI_API_KEY", combined)

    def test_runtime_configuration_is_not_hard_coded(self):
        source = Path("app.py").read_text(encoding="utf-8")

        self.assertNotRegex(source, r"OpenAI\(api_key=[\"']")
        self.assertNotRegex(source, r"model=[\"']")
        self.assertIn('os.environ.get("OPENAI_API_KEY"', source)
        self.assertIn('os.environ.get("OPENAI_MODEL"', source)

    def test_development_entrypoint_uses_app_port_without_debug(self):
        source = Path("app.py").read_text(encoding="utf-8")

        self.assertIn('os.environ.get("APP_PORT", "5000")', source)
        self.assertNotIn("debug=True", source)


if __name__ == "__main__":
    unittest.main()
