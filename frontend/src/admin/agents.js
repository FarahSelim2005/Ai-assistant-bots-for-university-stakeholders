// The agents an admin can add documents to. The values must match the agent keys in
// backend/app/agents/directory.py (each agent's documents live in data/raw/<value>/).
export const ADMIN_AGENTS = [
  { value: "graduation_advising", label: "Graduation & Advising" },
  { value: "hr_policies", label: "HR & Policies" },
  { value: "internship_career", label: "Internship & Career" },
  { value: "labs_research", label: "Labs & Research" },
];

export function agentLabel(value) {
  return ADMIN_AGENTS.find((agent) => agent.value === value)?.label ?? value;
}
