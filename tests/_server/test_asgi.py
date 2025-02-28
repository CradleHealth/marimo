import os
import tempfile
import unittest
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.testclient import TestClient
from starlette.websockets import WebSocket

from marimo._server.asgi import (
    ASGIAppBuilder,
    DynamicDirectoryMiddleware,
    create_asgi_app,
)

contents = """
import marimo

__generated_with = "0.0.1"
app = marimo.App()


@app.cell
def __():
    import marimo as mo
    print("Hello from placeholder")
    return mo,


if __name__ == "__main__":
    app.run()
"""


class TestASGIAppBuilder(unittest.TestCase):
    def setUp(self) -> None:
        # Create a temporary directory for the tests
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app1 = os.path.join(self.temp_dir.name, "app1.py")
        self.app2 = os.path.join(self.temp_dir.name, "app2.py")
        with open(self.app1, "w") as f:
            f.write(contents.replace("placeholder", "app1"))
        with open(self.app2, "w") as f:
            f.write(contents.replace("placeholder", "app2"))

    def tearDown(self) -> None:
        # Clean up the temporary directory
        self.temp_dir.cleanup()

    def test_create_asgi_app(self) -> None:
        builder = create_asgi_app(quiet=True, include_code=True)
        assert isinstance(builder, ASGIAppBuilder)

        builder = create_asgi_app(quiet=True, include_code=True)
        assert isinstance(builder, ASGIAppBuilder)

        builder = builder.with_app(path="/test", root=self.app1)
        app = builder.build()
        assert callable(app)

    def test_app_base(self) -> None:
        builder = create_asgi_app(quiet=True, include_code=True)
        builder = builder.with_app(path="/", root=self.app1)
        app = builder.build()
        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200
        assert "app1.py" in response.text

    def test_app_redirect(self) -> None:
        builder = create_asgi_app(quiet=True, include_code=True)
        builder = builder.with_app(path="/test", root=self.app1)
        app = builder.build()
        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200, response.text
        assert "app1.py" in response.text

    def test_multiple_apps(self) -> None:
        builder = create_asgi_app(quiet=True, include_code=True)
        builder = builder.with_app(path="/app1", root=self.app1)
        builder = builder.with_app(path="/app2", root=self.app2)
        app = builder.build()
        client = TestClient(app)
        response = client.get("/app1")
        assert response.status_code == 200, response.text
        assert "app1" in response.text
        response = client.get("/app2")
        assert response.status_code == 200, response.text
        assert "app2" in response.text
        response = client.get("/")
        assert response.status_code == 404, response.text
        response = client.get("/app3")
        assert response.status_code == 404, response.text

    def test_root_doesnt_conflict_when_root_is_last(self) -> None:
        builder = create_asgi_app(quiet=True, include_code=True)
        builder = builder.with_app(path="/app1", root=self.app1)
        builder = builder.with_app(path="/", root=self.app2)
        app = builder.build()
        client = TestClient(app)
        response = client.get("/app1")
        assert response.status_code == 200, response.text
        assert "app1.py" in response.text
        response = client.get("/")
        assert response.status_code == 200, response.text
        assert "app2.py" in response.text

    def test_root_doesnt_conflict_when_root_is_first(self) -> None:
        builder = create_asgi_app(quiet=True, include_code=True)
        builder = builder.with_app(path="/", root=self.app2)
        builder = builder.with_app(path="/app1", root=self.app1)
        app = builder.build()
        client = TestClient(app)
        response = client.get("/app1")
        assert response.status_code == 200, response.text
        assert "app1.py" in response.text
        response = client.get("/")
        assert response.status_code == 200, response.text
        assert "app2.py" in response.text

    def test_can_include_code(self) -> None:
        builder = create_asgi_app(quiet=True, include_code=True)
        builder = builder.with_app(path="/app1", root=self.app1)
        app = builder.build()
        client = TestClient(app)
        response = client.get("/app1")
        assert response.status_code == 200, response.text
        assert "app1.py" in response.text

    def test_can_hit_health(self) -> None:
        builder = create_asgi_app(quiet=True, include_code=True)
        builder = builder.with_app(path="/app1", root=self.app1)
        app = builder.build()
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 404, response.text
        response = client.get("/app1/health")
        assert response.status_code == 200, response.text


class TestDynamicDirectoryMiddleware(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for test files
        self.temp_dir = tempfile.mkdtemp()

        # Create some test files
        self.test_file = Path(self.temp_dir) / "test_app.py"
        self.test_file.write_text(contents)

        # Create nested directory structure
        nested_dir = Path(self.temp_dir) / "nested"
        nested_dir.mkdir()
        self.nested_file = nested_dir / "nested_app.py"
        self.nested_file.write_text(contents)

        # Create deeper nested structure
        deep_dir = nested_dir / "deep"
        deep_dir.mkdir()
        self.deep_file = deep_dir / "deep_app.py"
        self.deep_file.write_text("# Deep nested app")

        self.hidden_file = Path(self.temp_dir) / "_hidden.py"
        self.hidden_file.write_text(contents)

        # Create a base app that returns 404
        self.base_app = Starlette()

        async def catch_all(request: Request) -> Response:
            del request
            return PlainTextResponse("Not Found", status_code=404)

        self.base_app.add_route("/{path:path}", catch_all)

        # Create a simple app builder
        def app_builder(base_url: str, file_path: str) -> Starlette:
            del base_url
            app = Starlette()

            async def handle_assets(request: Request) -> Response:
                return PlainTextResponse(
                    f"Asset of {request.path_params['path']}"
                )

            app.add_route("/assets/{path:path}", handle_assets)

            async def handle(request: Request) -> Response:
                del request
                return PlainTextResponse(f"App from {Path(file_path).stem}")

            app.add_route("/{path:path}", handle)
            return app

        # Create the middleware
        self.app_with_middleware = DynamicDirectoryMiddleware(
            app=self.base_app,
            base_path="/apps",
            directory=self.temp_dir,
            app_builder=app_builder,
        )

        self.client = TestClient(self.app_with_middleware)

    def tearDown(self):
        # Clean up temp directory
        for root, dirs, files in os.walk(self.temp_dir, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(self.temp_dir)

    def test_non_matching_path_passes_through(self):
        response = self.client.get("/other/path")
        assert response.status_code == 404
        assert response.text == "Not Found"

    def test_missing_file_passes_through(self):
        response = self.client.get("/apps/nonexistent")
        assert response.status_code == 404
        assert response.text == "Not Found"

    def test_hidden_file_passes_through(self):
        response = self.client.get("/apps/_hidden")
        assert response.status_code == 404
        assert response.text == "Not Found"

    def test_valid_app_path(self):
        response = self.client.get("/apps/test_app/")
        assert response.status_code == 200
        assert response.text == "App from test_app"

    def test_missing_trailing_slash_redirects(self):
        response = self.client.get("/apps/test_app", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/apps/test_app/"

    def test_loading_assets(self):
        # Should not work before the app is created
        response = self.client.get("/apps/test_app/assets/marimo.css")
        assert response.status_code == 404

        # First request should create the app
        response = self.client.get("/apps/test_app/")
        assert response.status_code == 200

        response = self.client.get("/apps/test_app/assets/marimo.css")
        assert response.status_code == 200
        assert response.text == "Asset of marimo.css"

    def test_websocket_path_rewriting(self):
        # Create a WebSocket test app
        def ws_app_builder(base_url: str, file_path: str) -> Starlette:
            del base_url
            app = Starlette()

            async def websocket_endpoint(websocket: WebSocket) -> None:
                await websocket.accept()
                await websocket.send_text(f"WS from {Path(file_path).stem}")
                await websocket.close()

            app.add_websocket_route("/ws", websocket_endpoint)

            async def handle(request: Request) -> Response:
                del request
                return PlainTextResponse(f"App from {Path(file_path).stem}")

            app.add_route("/", handle)
            return app

        # Create middleware with WebSocket support
        ws_middleware = DynamicDirectoryMiddleware(
            app=self.base_app,
            base_path="/apps",
            directory=self.temp_dir,
            app_builder=ws_app_builder,
        )
        ws_client = TestClient(ws_middleware)

        # First request should create the app
        response = ws_client.get("/apps/test_app/")
        assert response.status_code == 200

        with ws_client.websocket_connect("/apps/test_app/ws") as websocket:
            data = websocket.receive_text()
            assert data == "WS from test_app"

    def test_app_caching(self):
        # First request should create the app
        response1 = self.client.get("/apps/test_app/")
        assert response1.status_code == 200

        # Get the cached app
        cached_app = self.app_with_middleware._app_cache[str(self.test_file)]

        # Second request should use the same app
        response2 = self.client.get("/apps/test_app/")
        assert response2.status_code == 200

        # Verify the app is still the same instance
        assert (
            self.app_with_middleware._app_cache[str(self.test_file)]
            is cached_app
        )

    def test_dynamic_file_addition(self):
        # Add a new file after middleware creation
        new_file = Path(self.temp_dir) / "new_app.py"
        new_file.write_text("# New app")

        # Should work with the new file
        response = self.client.get("/apps/new_app/")
        assert response.status_code == 200
        assert response.text == "App from new_app"

    def test_subpath_handling(self):
        # First request should create the app
        response = self.client.get("/apps/test_app/")
        assert response.status_code == 200
        assert response.text == "App from test_app"

        # Subpath should work
        response = self.client.get("/apps/test_app/subpath")
        assert response.status_code == 200
        assert response.text == "App from test_app"

    def test_query_params_preserved_in_redirect(self):
        response = self.client.get(
            "/apps/test_app?param=value", follow_redirects=False
        )
        assert response.status_code == 307
        assert response.headers["location"] == "/apps/test_app/?param=value"

    def test_nested_file_access(self):
        response = self.client.get("/apps/nested/nested_app/")
        assert response.status_code == 200
        assert response.text == "App from nested_app"

    def test_deep_nested_file_access(self):
        response = self.client.get("/apps/nested/deep/deep_app/")
        assert response.status_code == 200
        assert response.text == "App from deep_app"

    def test_nested_file_redirect(self):
        response = self.client.get(
            "/apps/nested/nested_app", follow_redirects=False
        )
        assert response.status_code == 307
        assert response.headers["location"] == "/apps/nested/nested_app/"

    def test_nested_file_with_query_params(self):
        response = self.client.get(
            "/apps/nested/nested_app?param=value", follow_redirects=False
        )
        assert response.status_code == 307
        assert (
            response.headers["location"]
            == "/apps/nested/nested_app/?param=value"
        )

    def test_nested_file_websocket(self):
        def ws_app_builder(base_url: str, file_path: str) -> Starlette:
            del base_url
            app = Starlette()

            async def websocket_endpoint(websocket: WebSocket) -> None:
                await websocket.accept()
                await websocket.send_text(f"WS from {Path(file_path).stem}")
                await websocket.close()

            app.add_websocket_route("/ws", websocket_endpoint)

            async def handle(request: Request) -> Response:
                del request
                return PlainTextResponse(f"App from {Path(file_path).stem}")

            app.add_route("/", handle)
            return app

        ws_middleware = DynamicDirectoryMiddleware(
            app=self.base_app,
            base_path="/apps",
            directory=self.temp_dir,
            app_builder=ws_app_builder,
        )
        ws_client = TestClient(ws_middleware)

        # First request should create the app
        response = ws_client.get("/apps/nested/nested_app/")
        assert response.status_code == 200

        with ws_client.websocket_connect(
            "/apps/nested/nested_app/ws"
        ) as websocket:
            data = websocket.receive_text()
            assert data == "WS from nested_app"

    def test_nonexistent_nested_path(self):
        response = self.client.get("/apps/nested/nonexistent/")
        assert response.status_code == 404
        assert response.text == "Not Found"
