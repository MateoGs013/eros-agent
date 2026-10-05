import hashlib
from abc import ABC, abstractmethod
from eros.models import JobOffer


class BaseJobSource(ABC):
    """Clase base abstracta para cualquier fuente o conector de ofertas."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre identificador de la fuente (ej. 'getonboard')."""
        pass

    @abstractmethod
    async def fetch_jobs(self) -> list[JobOffer]:
        """Obtiene y normaliza la lista de ofertas disponibles."""
        pass

    def generate_job_id(self, external_id: str) -> str:
        """Genera un hash determinista para identificar la oferta."""
        raw = f"{self.name}:{external_id}".lower()
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
