# Author: Team 04
# This file is developed by our team

from __future__ import annotations

import logging
from logging.config import dictConfig

from flask import Flask


def configure_logging(app: Flask, debug: bool) -> None:
    level = "DEBUG" if debug else "INFO"
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
                }
            },
            "handlers": {
                "wsgi": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                }
            },
            "root": {"level": level, "handlers": ["wsgi"]},
        }
    )

    # Make Flask's logger consistent with root.
    app.logger.setLevel(logging.getLogger().level)

