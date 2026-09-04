def create_app(test_config=None):
    """Lazy import keeps calculation/import helpers usable without Flask installed."""
    from .web import create_app as application_factory

    return application_factory(test_config)
