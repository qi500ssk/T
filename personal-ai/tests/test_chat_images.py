import base64

from apps.api.main import app
from core.chat.gateway import MockProvider


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _upload(client, name: str = "pixel.png") -> dict:
    response = client.post(
        "/api/chat/images",
        files={"file": (name, PNG_1X1, "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_chat_image_upload_preview_and_staged_delete(client):
    image = _upload(client)
    assert image["mime_type"] == "image/png"
    assert image["width"] == 1
    assert image["height"] == 1

    content = client.get(f"/api/chat/images/{image['id']}/content")
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("image/png")
    assert content.content == PNG_1X1

    assert client.delete(f"/api/chat/images/{image['id']}").status_code == 200
    assert client.get(f"/api/chat/images/{image['id']}/content").status_code == 404


def test_chat_image_rejects_disguised_or_mismatched_files(client):
    disguised = client.post(
        "/api/chat/images",
        files={"file": ("fake.png", b"not an image", "image/png")},
    )
    assert disguised.status_code == 415

    mismatch = client.post(
        "/api/chat/images",
        files={"file": ("pixel.jpg", PNG_1X1, "image/jpeg")},
    )
    assert mismatch.status_code == 415


def test_non_visual_model_rejects_chat_images(client):
    image = _upload(client)
    conversation = client.post("/api/conversations", json={}).json()
    response = client.post(
        "/api/chat",
        json={
            "conversation_id": conversation["id"],
            "message": "这是什么？",
            "image_ids": [image["id"]],
        },
    )
    assert response.status_code == 422
    assert "qwen3.8-max" in response.json()["detail"]


def test_qwen_image_is_bound_to_message_and_sent_as_data_url(client):
    image = _upload(client)
    created = client.post(
        "/api/settings/models",
        json={
            "name": "Qwen 视觉测试",
            "provider": "mock",
            "base_url": "",
            "model": "qwen3.8-max",
            "timeout_seconds": 30,
        },
    )
    assert created.status_code == 200, created.text
    model_id = created.json()["id"]
    assert client.patch(
        "/api/settings/models/selection", json={"model_id": model_id}
    ).status_code == 200

    capture = MockProvider(delay=0)
    captured_messages: list[list[dict]] = []
    original_stream = capture.stream

    async def recording_stream(messages, temperature=0.7, tools=None):
        captured_messages.append(messages)
        async for chunk in original_stream(messages, temperature, tools):
            yield chunk

    capture.stream = recording_stream
    previous_provider = app.state.provider
    app.state.provider = capture
    try:
        conversation = client.post("/api/conversations", json={}).json()
        response = client.post(
            "/api/chat",
            json={
                "conversation_id": conversation["id"],
                "message": "识别这张图片",
                "image_ids": [image["id"]],
                "model_id": model_id,
            },
        )
        assert response.status_code == 200
        assert "event: run.completed" in response.text
    finally:
        app.state.provider = previous_provider

    user_content = captured_messages[0][-1]["content"]
    assert isinstance(user_content, list)
    image_part = next(item for item in user_content if item["type"] == "image_url")
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")

    messages = client.get(f"/api/conversations/{conversation['id']}/messages").json()
    assert messages[0]["images"][0]["id"] == image["id"]
    assert client.delete(f"/api/chat/images/{image['id']}").status_code == 409
    assert client.delete(f"/api/conversations/{conversation['id']}").status_code == 200
    assert client.get(f"/api/chat/images/{image['id']}/content").status_code == 404


def test_planning_document_mode_accepts_images_with_visual_model(client):
    image = _upload(client)
    created = client.post(
        "/api/settings/models",
        json={
            "name": "规划视觉测试",
            "provider": "mock",
            "base_url": "",
            "model": "qwen3.8-max",
            "timeout_seconds": 30,
        },
    )
    assert created.status_code == 200
    conversation = client.post("/api/conversations", json={}).json()
    response = client.post(
        "/api/chat",
        json={
            "conversation_id": conversation["id"],
            "message": "识别图片",
            "image_ids": [image["id"]],
            "execution_mode": "planned",
            "model_id": created.json()["id"],
        },
    )
    assert response.status_code == 200
    assert "event: planning.document.completed" in response.text
