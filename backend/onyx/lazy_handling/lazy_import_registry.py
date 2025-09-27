from backend.onyx.lazy_handling.lazy_module import LazyModule
from backend.onyx.lazy_handling.lazy_module import TYPE_CHECKING

if TYPE_CHECKING:
    import vertexai

lazy_vertexai: "vertexai" = LazyModule("vertexai")
