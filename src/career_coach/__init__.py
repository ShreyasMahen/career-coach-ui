"""Career Coach application packages; importing this module does not load ML models."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

# Preserve the requested on-disk name while providing a valid Python package name.
_name = f"{__name__}.data_extraction"
_spec = spec_from_file_location(_name, Path(__file__).with_name("data-extraction") / "__init__.py")
if _spec is None or _spec.loader is None:
    raise ImportError("Cannot locate the data extraction package")
data_extraction = module_from_spec(_spec)
sys.modules[_name] = data_extraction
_spec.loader.exec_module(data_extraction)
