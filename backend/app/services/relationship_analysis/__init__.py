from enum import Enum, auto
from dataclasses import dataclass
from typing import Dict, List, Set, Optional, Type, Any


class RelationshipType(Enum):
    FUNCTION_CALL = auto()
    TEMPLATE_RENDER = auto()
    MODEL_ACCESS = auto()
    URL_ROUTE = auto()
    INHERITANCE = auto()
    IMPLEMENTS = auto()
    DEPENDENCY_INJECTION = auto()
    EVENT_HANDLER = auto()
    ASYNC_AWAIT = auto()
    GENERIC = auto()


@dataclass
class Relationship:
    source: str
    target: str
    type: RelationshipType
    metadata: Dict = None
    confidence: float = 1.0
    context: List[str] = None
