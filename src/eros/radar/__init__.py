"""Módulo TrendRadar de Eros Agent.
Radar de tendencias tecnológicas, blogs de ingeniería, GitHub y noticias
como punto de partida de los artículos del portafolio.
"""

from .models import TrendItem, TrendSource, TrendStatus
from .engine import RadarEngine
from .storage import RadarStorage

__all__ = ["TrendItem", "TrendSource", "TrendStatus", "RadarEngine", "RadarStorage"]
