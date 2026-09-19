import canvasapi_async


def test_public_names() -> None:
    """The package exports the Canvas class and the two background-loop functions."""
    assert canvasapi_async.__all__ == ["Canvas", "configure", "shutdown"]

    for name in canvasapi_async.__all__:
        assert getattr(canvasapi_async, name) is not None
