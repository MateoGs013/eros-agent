"""Módulo TrendRadar de Eros Agent.
Radar de tendencias tecnológicas, blogs de ingeniería, GitHub y noticias
para generación de contenido técnico y artículos de alta señal.
"""

from .models import TrendItem, TrendSource, TrendStatus
from .engine import RadarEngine
from .storage import RadarStorage

__all__ = ["TrendItem", "TrendSource", "TrendStatus", "RadarEngine", "RadarStorage"]
