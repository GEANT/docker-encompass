"""
Django logging configuration for Encompass.
"""

import logging


class IgnoreHealthzFilter(logging.Filter):
    """
    class used by logging handler
    """
    def filter(self, record):
        try:
            return "/healthz" not in record.getMessage()
        except Exception:  # pylint: disable=broad-except
            return True
