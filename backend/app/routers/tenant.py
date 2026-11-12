"""GET /tenant: the current university as the frontend shows it: its name, logo, colours,
start screen texts and audiences, and its live assistants with the skills that work here
(the frontend shows the CV button, the voice button and the campus map from these).
"{university}" in texts is replaced by the university's short name."""
from fastapi import APIRouter

from app import tenants
from app.agents import agents_of
from app.rag.prompts import render

router = APIRouter()


@router.get("/tenant")
def current_tenant():
    tenant = tenants.current()
    text = lambda value: render(value or "", tenant.short)
    assistants = [{
        "id": agent.name,
        "template_key": agent.settings.template_key,  # old links (/?agent=labs_research) still work
        "name": agent.display_name,
        "summary": text(agent.settings.summary),
        "subtitle": text(agent.settings.subtitle),
        "welcome": text(agent.settings.welcome),
        "placeholder": text(agent.settings.placeholder),
        "examples": [text(example) for example in agent.settings.examples],
        "audiences": list(agent.allowed_user_types),
        "skills": agent.active_skills(),
    } for agent in agents_of(tenant.id) if agent.live]
    return {
        "slug": tenant.slug,
        "name": tenant.name,
        "short_name": tenant.short,
        "logo_url": tenant.logo_url,
        "colors": {"primary": tenant.brand_primary, "accent": tenant.brand_accent, "dark": tenant.brand_dark},
        "intro": text(tenant.intro),
        "audiences": [{**audience, "text": text(audience.get("text"))} for audience in tenant.audiences],
        "assistants": assistants,
    }
