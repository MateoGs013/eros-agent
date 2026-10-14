import unittest
import html
import tempfile
import shutil
from unittest.mock import AsyncMock, MagicMock, patch

from eros.models import TailoredCV, CVProject, CVEducation
from eros.hunter.cv_generator import CVGenerator
from eros.hunter.sources.linkedin import LinkedInJobsSource


class TestAuditRemediations(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.generator = CVGenerator()

    def test_01_harvard_ats_cv_xss_escaping(self):
        xss_payload = "<script>alert('xss')</script>"
        cv = TailoredCV(
            language="es",
            name=f"Mateo {xss_payload}",
            title=f"Engineer {xss_payload}",
            summary=f"Summary with {xss_payload}",
            location="Argentina",
            email="mateo@example.com",
            phone="+5492990000000",
            linkedin="https://linkedin.com/in/mateo",
            github="https://github.com/mateo",
            portfolio="https://mateogs.tech",
            skills={
                f"Cat {xss_payload}": [f"Skill {xss_payload}", "Vue 3"]
            },
            experience=[
                CVProject(
                    title=f"Project {xss_payload}",
                    role="Tech Lead",
                    period="2024 - Present",
                    location="Remote",
                    bullets=[f"Led architecture with {xss_payload}"],
                    tech_stack=[f"TypeScript {xss_payload}", "Node.js"]
                )
            ],
            education=[
                CVEducation(
                    institution=f"Institute {xss_payload}",
                    degree="Software Engineering",
                    period="2022 - 2026",
                    details=f"Honors with {xss_payload}"
                )
            ],
            languages=[f"Spanish {xss_payload}"],
            methodologies=[f"Scrum {xss_payload}"]
        )

        rendered_html = self.generator.render_harvard_html(cv)

        # Unescaped payload must NEVER be in the rendered HTML
        self.assertNotIn("<script>alert('xss')</script>", rendered_html)
        # Escaped version must be present
        self.assertIn("&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;", rendered_html)

    async def test_02_linkedin_source_resilience_on_429_or_network_error(self):
        source = LinkedInJobsSource()
        mock_resp_list = MagicMock()
        mock_resp_list.status_code = 200
        mock_resp_list.text = """
        <div class="base-card relative w-full hover:no-underline">
            <h3 class="base-search-card__title">Senior Frontend Engineer</h3>
            <h4 class="base-search-card__subtitle"><a href="#">Globex</a></h4>
            <span class="job-search-card__location">Remoto</span>
            <a class="base-card__full-link" href="https://ar.linkedin.com/jobs/view/1234567890"></a>
        </div>
        """

        mock_resp_detail = MagicMock()
        mock_resp_detail.status_code = 429  # Rate limit simulation
        mock_resp_detail.text = "Too Many Requests"

        async def mock_get(url, *args, **kwargs):
            if "jobPosting" in url:
                return mock_resp_detail
            return mock_resp_list

        with patch("httpx.AsyncClient.get", side_effect=mock_get):
            # Must not raise UnboundLocalError
            jobs = await source.fetch_jobs()
            self.assertIsInstance(jobs, list)


if __name__ == "__main__":
    unittest.main()
