"""cogmem — когнитивная память по образцу человеческой.

Главный вход — класс :class:`cogmem.memory.CognitiveMemory`.
"""

from cogmem.config import MemoryConfig
from cogmem.clock import Clock, FakeClock, SystemClock

__all__ = ["MemoryConfig", "Clock", "FakeClock", "SystemClock"]
