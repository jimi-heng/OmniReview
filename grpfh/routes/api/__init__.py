from __future__ import annotations

from flask import Blueprint


bp = Blueprint("api", __name__)

# Import modules so their route decorators attach to `bp`.
from . import auth as _auth  # noqa: F401
from . import projects as _projects  # noqa: F401
from . import literatures as _literatures  # noqa: F401
from . import screening as _screening  # noqa: F401
from . import fulltext as _fulltext  # noqa: F401
from . import extraction as _extraction  # noqa: F401

