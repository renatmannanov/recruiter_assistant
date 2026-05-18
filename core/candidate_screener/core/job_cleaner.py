"""Clean Apify job JSON before sending to LLM screener.

curious_coder/linkedin-jobs-scraper returns ~35 fields per job; most are noise
for screening. This module extracts the subset we actually use and normalizes
the recruiter contact (top-level jobPoster* fields → nested dict).

Field names are based on real curious_coder output captured in
_baseline_cv_to_jobs/curious_coder_sample.json (step_0). If LinkedIn or
the actor changes its schema, update the .get() keys here.
"""


def clean_job(job: dict) -> dict:
    """Strip Apify job JSON to essential fields.

    Resilient to missing fields — all reads via .get() with safe defaults.

    Returns a dict with stable keys regardless of source-side variation:
        title, company, company_linkedin_url, location, jd_text,
        seniority, employment_type, work_remote_allowed, posted_at,
        applicants, linkedin_url, job_id, recruiter (or None),
        company_details (or None).
    """
    # Recruiter contact: curious_coder uses top-level jobPoster* fields.
    # Older actor schemas / planners assumed nested "recruiter" or "posterFullName" —
    # we accept both for forward compatibility, but jobPoster* is the actual one.
    recruiter = None
    poster_name = job.get("jobPosterName") or job.get("posterFullName")
    if poster_name:
        recruiter = {
            "name": poster_name,
            "title": job.get("jobPosterTitle") or job.get("posterTitle") or "",
            "linkedin_url": job.get("jobPosterProfileUrl") or job.get("posterLinkedinUrl") or "",
            "photo": job.get("jobPosterPhoto") or "",
        }

    # Company details — present when the actor was called with scrapeCompany=True.
    company_details = None
    if job.get("companyDescription") or job.get("companyEmployeesCount"):
        company_details = {
            "description": job.get("companyDescription") or "",
            "website": job.get("companyWebsite") or "",
            "employees_count": job.get("companyEmployeesCount"),
            "slogan": job.get("companySlogan") or "",
            "address": job.get("companyAddress") or {},
        }

    return {
        "job_id": job.get("id") or "",
        "title": job.get("title") or "",
        "company": job.get("companyName") or "",
        "company_linkedin_url": job.get("companyLinkedinUrl") or "",
        "location": job.get("location") or "",
        # Description: prefer plain text; fall back to HTML if only that exists.
        "jd_text": job.get("descriptionText") or job.get("descriptionHtml") or "",
        "seniority": job.get("seniorityLevel") or "",
        "employment_type": job.get("employmentType") or "",
        "work_remote_allowed": job.get("workRemoteAllowed", False),
        "posted_at": job.get("postedAt") or "",
        "applicants": job.get("applicantsCount") or "",
        "linkedin_url": job.get("link") or "",
        "recruiter": recruiter,
        "company_details": company_details,
    }
