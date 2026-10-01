"""Loads the private production parameters if present, otherwise the public placeholders."""
try:
    from parametros import *          # noqa: F401,F403  (private, not published)
    PRIVADOS = True
except ImportError:
    from parametros_ejemplo import *  # noqa: F401,F403
    PRIVADOS = False
