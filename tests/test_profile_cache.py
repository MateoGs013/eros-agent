"""El perfil del portafolio con campos en lista no rompe el arranque (incidente del 2-nov-2026).

El documento «about» publica `languages` como lista. Eros lo asignaba sin validar, lo
guardaba en la caché y al reiniciar no podía leerla: la app no arrancaba.
"""

import asyncio
import json
import os
import shutil
import tempfile
import unittest

from eros.db.storage import JobStorage
from eros.models import ProfileContext

LANGUAGES = ["Español (nativo)", "Inglés (B2 profesional técnico)"]


class ProfileListFieldsTest(unittest.TestCase):
    def test_lista_asignada_se_une_en_texto(self):
        profile = ProfileContext()
        profile.languages = LANGUAGES
        self.assertEqual(profile.languages, "Español (nativo) · Inglés (B2 profesional técnico)")

    def test_lista_al_construir_y_null(self):
        profile = ProfileContext(languages=LANGUAGES, role=None)
        self.assertEqual(profile.languages, "Español (nativo) · Inglés (B2 profesional técnico)")
        self.assertEqual(profile.role, "")


class ProfileCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.storage = JobStorage(db_path=os.path.join(self.tmp, "eros.db"))
        asyncio.run(self.storage.init_db())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_raw(self, data: str) -> None:
        import aiosqlite

        async def write():
            async with aiosqlite.connect(self.storage.db_path) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO profile_cache (key, data, updated_at) VALUES ('main', ?, ?)",
                    (data, "2026-11-02T00:00:00+00:00"),
                )
                await db.commit()

        asyncio.run(write())

    def test_cache_vieja_con_lista_se_trata_como_vacia(self):
        # La forma exacta que dejó guardada la versión anterior en producción.
        stale = ProfileContext().model_dump()
        stale["languages"] = LANGUAGES
        self._write_raw(json.dumps(stale))
        # Con el validador nuevo la lista se lee como texto; si no se pudiera, sería None.
        cached = asyncio.run(self.storage.get_profile_cache())
        self.assertIsNotNone(cached)
        self.assertIn("Español (nativo)", cached.languages)

    def test_cache_ilegible_no_rompe(self):
        self._write_raw(json.dumps({"projects": "no es una lista"}))
        self.assertIsNone(asyncio.run(self.storage.get_profile_cache()))

    def test_ida_y_vuelta(self):
        profile = ProfileContext()
        profile.languages = LANGUAGES
        asyncio.run(self.storage.save_profile_cache(profile))
        self.assertEqual(asyncio.run(self.storage.get_profile_cache()).languages, profile.languages)


if __name__ == "__main__":
    unittest.main()
